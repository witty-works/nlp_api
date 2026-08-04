"""Utilities for alternatives generation and formatting."""

from app.models import (
    LangType,
    FrenchGenderSeparatorType,
    Alternative,
    INKLUSIVUM_SEPARATOR,
)


def article_binary_pair(
    static_rules: dict, lang: LangType, article: str
) -> tuple[str, str]:
    if lang == LangType.FR and article in static_rules[lang]["inclusive_articles"]:
        masculine_base = static_rules[lang]["articles_map"][article]
        male_article = masculine_base
        female_article = static_rules[lang]["articles_binary_map"][masculine_base]
        return male_article, female_article

    if article in static_rules[lang].get("masculine_articles", {}):
        return article, static_rules[lang]["articles_binary_map"][article]

    # assume feminine
    return static_rules[lang]["articles_binary_map"][article], article


def splice_separator(text: str, separator: str) -> str:
    """Put the configured separator where a slash is standing in for it.

    The Inklusivum has no separator, so nothing is spliced. Going through here
    rather than calling replace directly is what keeps its placeholder out of
    the text: it once shipped "ihremDEEseinem" to users.
    """
    if separator == INKLUSIVUM_SEPARATOR:
        return text

    return text.replace("/", separator)


def inklusivum_article(forms: dict, form: str | None = None) -> str | None:
    """Pick the Inklusivum article out of a per-case paradigm.

    Most paradigms collapse to a single form once gender is dropped, so the
    case is only needed for the few that do not. Callers that know the case
    pass it; the nominative stands in otherwise.
    """
    if not forms:
        return None

    if form is not None and form in forms:
        return forms[form]

    distinct = set(forms.values())
    if len(distinct) == 1:
        return distinct.pop()

    return forms.get("nominativ")


def get_noun_conjunction(static_rules: dict, lang: LangType, is_singular: bool) -> str:
    return (
        static_rules[lang]["noun_conjunction"]["singular"]
        if is_singular
        else static_rules[lang]["noun_conjunction"]["plural"]
    )


def add_german_prefix(word: str, prefix: str) -> str:
    if not prefix or word.startswith(prefix):
        return word

    if not word.startswith("-") and not prefix.endswith("-"):
        word = word[0].lower() + word[1:]

    return prefix + word


def add_article(lang: LangType, text: str, article: str, separator: str) -> str:
    if (
        lang == LangType.FR
        and (article.endswith("le") or article == "la")
        and text[0] in ["a", "e", "i", "o", "u", "h"]
    ):
        return "l'" + text

    if separator != FrenchGenderSeparatorType.POINT_MEDIAN:
        article = article.replace(FrenchGenderSeparatorType.POINT_MEDIAN, separator)

    return article + " " + text


def get_article_by_index(
    static_rules: dict, lang: LangType, articles_list: str, article_index: int
):
    return list(static_rules[lang][articles_list].keys())[article_index]


def build_french_adjective_alternatives(
    male_form: str, female_form: str
) -> list[Alternative]:
    lemma = male_form + "~" + female_form
    return [
        Alternative(
            lemma,
            [lemma],
            [
                {
                    "word_type": "a",
                    "lower_case": True,
                    "lemmatize": True,
                }
            ],
            False,
            False,
            False,
            False,
            False,
            True,
        )
    ]
