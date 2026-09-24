"""How each German gender format writes a gendered form.

The separator formats (`german_gender_ending` other than the Inklusivum) differ
only in how they join the parts of a form, so converting between them is
reading the parts out of one spelling and writing them in another. There are
three kinds of form:

- a noun ending: `Lehrer*innen`, `LehrerInnen`, `Lehrer(innen)`, `Angestellte*r`;
- an article or pronoun pair: `die*der`, `der/die`, `ihr*sein`;
- a word with a short ending: `jede*r`, `ein*e`, `ihre*n`.

The pairs and short endings come from the `Alternative` column of
training_data/de/articles.csv (`die~der`, `jede~r`, ...), so a lowercase word
with a separator in it is only taken for one when the table knows it.
"""

import re

from app.categories import is_sub_category_enabled
from app.models import Config, GermanGenderEndingType as Ending, LangType

# What joins the parts, per format, for noun endings.
NOUN_SEPARATORS = {
    Ending.STAR: "*",
    Ending.UNDERSCORE: "_",
    Ending.COLON: ":",
    Ending.SLASH: "/",
    Ending.SLASH_DASH: "/-",
}

# Article and pronoun pairs: the three infix formats use their own separator,
# the others write them with a slash (Die/der LehrerIn, die/der Lehrer(in)).
PAIR_SEPARATORS = {
    Ending.STAR: "*",
    Ending.UNDERSCORE: "_",
    Ending.COLON: ":",
    Ending.SLASH: "/",
    Ending.SLASH_DASH: "/",
    Ending.CAPITAL_LETTER: "/",
    Ending.PARENTHESIS: "/",
    Ending.PARENTHESIS_DASH: "/",
}

_ENDING_PREFIX = re.compile(r"^(?:/-|[*_:/]|\(-?)")
_GENDER_PART = re.compile(r"^(innen|in|r|nja|ze|iza|eza)(.*)$", re.S)

# Compounds with the marker inside, for the formats that keep them in one
# token: `Mitarbeiter*innengespräch`, `Lehrer:innen-Team`.
COMPOUND_PATTERNS = {
    ending: re.compile(
        rf"^[A-ZÄÖÜ][a-zäöüß]+{re.escape(separator)}innen(?:[a-zäöüß]+|-\w[\w-]*)$"
    )
    for ending, separator in (
        (Ending.STAR, "*"),
        (Ending.UNDERSCORE, "_"),
        (Ending.COLON, ":"),
    )
}


def noun_ending(text: str) -> str:
    """A gendered noun ending, however it is written: `*innen`, `/-in`,
    `(innen)`, `(-in)`, `Innen` all give `innen`/`in`. The rest of a compound
    is kept as written (`*innen-Team` gives `innen-Team`)."""
    ending = _ENDING_PREFIX.sub("", text)
    if ending.endswith(")"):
        ending = ending[:-1]

    # Only a Binnen-I capital belongs to the ending itself.
    return ending[:1].lower() + ending[1:]


def feminine_form(check_text: str) -> str | None:
    """The single word a gendered noun stands for, to look it up:
    `Lehrer*innen` and `Lehrer/innengespräch` give `Lehrerin`,
    `Angestellte(r)` gives `Angestellter`. None when there is no marker."""
    match = re.match(r"^(.+?)(?:/-|[*_:/]|\(-?|(?=I))([A-Za-zäöü]+)", check_text)
    if match is None:
        return None

    stem, ending = match.group(1), match.group(2).lower()
    gender = _GENDER_PART.match(ending)
    if gender is None:
        return None

    return stem + ("in" if gender.group(1).startswith("in") else gender.group(1))


def render_noun_ending(ending: str, target: Ending) -> str | None:
    """`innen` in the target format: `*innen`, `Innen`, `(innen)`, ...; for a
    compound (`innengespräch`) only the gender part is marked, so brackets
    close before the rest of the word: `(innen)gespräch`."""
    match = _GENDER_PART.match(ending)
    gender, rest = (match.group(1), match.group(2)) if match else (ending, "")

    if target in NOUN_SEPARATORS:
        return NOUN_SEPARATORS[target] + gender + rest
    if target == Ending.CAPITAL_LETTER:
        # LehrerInnen; an ending the capital I cannot mark (Angestellte/r) is
        # written with a slash, as Binnen-I texts do, so it reads back too.
        if gender.startswith("in"):
            return gender[:1].upper() + gender[1:] + rest
        return "/" + gender + rest
    if target == Ending.PARENTHESIS:
        return f"({gender}){rest}"
    if target == Ending.PARENTHESIS_DASH:
        return f"(-{gender}){rest}"

    return None


def render_word_ending(stem: str, ending: str, target: Ending) -> str | None:
    """A word with a short ending in the target format: `jede` + `r` gives
    `jede*r`, `jede/r`, `jede(r)`."""
    if target == Ending.CAPITAL_LETTER:
        return f"{stem}/{ending}"
    rendered = render_noun_ending(ending, target)

    return None if rendered is None else stem + rendered


def render_pair(first: str, second: str, target: Ending) -> str | None:
    """An article or pronoun pair in the target format, in the writer's order."""
    separator = PAIR_SEPARATORS.get(target)

    return None if separator is None else f"{first}{separator}{second}"


_WORD = r"[A-ZÄÖÜa-zäöüß][a-zäöüß]*"


def split_form(text: str) -> tuple[str, str] | None:
    """The two parts of a form written with any separator format: `die*der`,
    `Der/Die`, `jede/-r`, `jede(r)`, `ein(-e)`. Case is kept."""
    match = re.fullmatch(rf"({_WORD})(?:/-|[*_:/])({_WORD})", text)
    if match is None:
        match = re.fullmatch(rf"({_WORD})\(-?({_WORD})\)", text)

    return None if match is None else (match.group(1), match.group(2))


def convert_form(
    text: str, target: Ending, inclusive_forms: set[str], words: set[str]
) -> str | None:
    """A lowercase pair or short-ending form in the target format, or None
    when it is not one the article table knows. `words` are the plain article
    and pronoun forms, to tell `jede~r` (jeder is a word) from `sie~er`. Case
    of the first letter is kept, so a form opening a sentence stays so."""
    parts = split_form(text)
    if parts is None:
        return None

    # Looked up in lowercase; written back as the writer wrote it, so a pair
    # opening a sentence (`Der/die`) or in title case (`Der*Die`) keeps that.
    first, second = parts
    lower_first, lower_second = first.lower(), second.lower()
    if not (
        f"{lower_first}~{lower_second}" in inclusive_forms
        or f"{lower_second}~{lower_first}" in inclusive_forms
    ):
        return None

    if lower_first + lower_second in words:
        return render_word_ending(first, second, target)

    return render_pair(first, second, target)


# What can follow a slash or bracket in a gendered form. Nouns take the
# feminine ending (`Lehrer/innen`, `Angestellte(r)`); pronouns and articles
# also short ones (`ihre/n`, `jede/-r`). A capitalised word before `/n` is a
# plural hint (`Klasse/n`), not a gendered form.
NOUN_GENDER_ENDINGS = {"in", "innen", "r"}
WORD_GENDER_ENDINGS = NOUN_GENDER_ENDINGS | {"e", "n", "s", "m", "er", "en", "em", "es"}


def gendered_form_end(tokens, index: int) -> int | None:
    """If the token is the first part of a form the tokenizer split (`Lehrer`
    `/` `innen`, `Lehrer` `(` `innen` `)`, `ihre` `/` `n`), the index of its
    last token; None when it is a word of its own."""
    token = tokens[index]
    if token.whitespace_ or index + 2 >= len(tokens):
        return None

    separator = tokens[index + 1].text
    if separator not in ("/", "("):
        return None

    endings = NOUN_GENDER_ENDINGS if token.text[:1].isupper() else WORD_GENDER_ENDINGS
    if tokens[index + 2].text.lstrip("-").lower() not in endings:
        return None

    last = index + 2
    if separator == "(" and last + 1 < len(tokens) and tokens[last + 1].text == ")":
        last += 1

    return last


def is_gendered_stem(tokens, index: int) -> bool:
    """Whether the token is the first part of a split gendered form, and so
    not a masculine word of its own."""
    return gendered_form_end(tokens, index) is not None


def bulk_actions(lang: str, config: Config) -> list[str]:
    """The `bulk` groups a check in this language with this config can return.

    Switching the gender format needs German, a separator format (not the
    Inklusivum yet), inclusive roles, and the mismatch subcategory enabled:
    the same conditions under which the rules produce its alerts.
    """
    supported = (
        lang == LangType.DE and config.german_gender_ending != Ending.INKLUSIVUM
    ) or (lang == LangType.FR)
    if (
        supported
        and Config.gendered_roles_format_inclusive(config.gendered_roles_format)
        and is_sub_category_enabled(
            config.disabled_categories, "gendered_denominations_ending_advanced"
        )
    ):
        return ["gender_format"]

    return []


# A masculine right before a coordinated feminine is the first half of a pair
# formula the rules did not recognise, most often because of a typo in the
# second half (`Schüler und Schüllerinnen`): gendering the first half alone
# would leave `Schüler:innen und Schüllerinnen`.
_PAIR_TAIL = r"\s+(?:und|oder|bzw\.|sowie|&)\s+[\w-]*?in(?:nen)?\b"

# Roles written in the generic masculine: job titles, functions, leadership.
# Address forms (`Frau Meier`), pronouns and identity terms name a particular
# person and stay one-by-one.
_ROLE_SUBCATEGORIES = {"titles", "function", "leadership"}


def mark_masculines_for_bulk(results: list, text: str, lang: str = LangType.DE) -> None:
    """Add generic masculines and pair formulas to the gender format switch.

    Every role alert offering the gender-inclusive form in the configured
    format (`Der Lehrer` -> `Die:der Lehrer:in`, `Schüler und Schülerinnen` ->
    `Schüler:innen`) is marked with `bulk_alternative` pointing at it, so
    "switch the gender format" also genders what was written in the generic
    masculine. Left out: feminine forms (`Die Lehrerin`, often a particular
    woman), a masculine that starts an unrecognised pair formula, and anything
    overlapping an alert already in the switch.
    """
    taken = [(result.start, result.end) for result in results if result.bulk]

    for result in sorted(results, key=lambda result: result.start):
        if result.bulk or result.category != "gender-orientation":
            continue

        index = next(
            (
                i
                for i, alternative in enumerate(result.alternatives or [])
                if alternative.gender_role == "inclusive_gender" and alternative.text
            ),
            None,
        )
        if index is None:
            continue

        role = (result.subcategory or "").removesuffix("_advanced")
        # A pair formula comes as `gendered_denominations_ending`, or with the
        # `_advanced` suffix when binary forms are also suggested.
        is_pair = role == "gendered_denominations_ending"
        if not is_pair and role not in _ROLE_SUBCATEGORIES:
            continue
        # German feminine forms and unrecognised pair formulas; French
        # feminines come as `gender_identity`, outside the role subcategories.
        if lang == LangType.DE and not is_pair:
            last_word = result.text.split()[-1] if result.text.split() else ""
            if re.search(r"in(?:nen)?$", last_word):
                continue
            if re.search(re.escape(result.text) + _PAIR_TAIL, text):
                continue
        if any(start < result.end and result.start < end for start, end in taken):
            continue

        result.bulk = "gender_format"
        result.bulk_alternative = index
        taken.append((result.start, result.end))


# --- French -----------------------------------------------------------------
#
# French inclusive forms join a masculine word and a feminine suffix, and the
# six `french_gender_separator` formats differ in the separator (`·`, `.`,
# `/`) and in whether a plural `s` takes one of its own: `enseignant·es` or
# `enseignant·e·s`. Articles come as pairs (`la·le`) or with an ending (`un·e`).

_FR = "a-zàâäçéèêëîïôöùûüÿœæ"
_FR_WORD = rf"[{_FR.upper()}{_FR}][{_FR}]*"

# Feminine suffixes as inclusive writing uses them, longest first so `rice`
# is not read as `e`.
FRENCH_FEMININE_SUFFIXES = sorted(
    [
        "e",
        "rice",
        "trice",
        "ice",
        "euse",
        "se",
        "ne",
        "le",
        "te",
        "ère",
        "ière",
        "esse",
        "ve",
        "ive",
        "fe",
        "enne",
        "ienne",
        "onne",
        "ette",
        "elle",
        "eure",
        "ale",
    ],
    key=len,
    reverse=True,
)


def split_french_ending(ending: str) -> tuple[str, bool] | None:
    """A feminine suffix and whether a plural `s` follows it: `es` gives
    (`e`, True), `rices` (`rice`, True), `rice` (`rice`, False)."""
    if ending in FRENCH_FEMININE_SUFFIXES:
        return ending, False
    if ending.endswith("s") and ending[:-1] in FRENCH_FEMININE_SUFFIXES:
        return ending[:-1], True

    return None


def render_french(stem: str, suffix: str, plural: bool, target: str) -> str:
    """A French inclusive form in a `french_gender_separator` format."""
    separator = target[0]
    if not plural:
        return f"{stem}{separator}{suffix}"
    if len(target) > 1:
        # The `s` formats: enseignant·e·s
        return f"{stem}{separator}{suffix}{separator}s"

    return f"{stem}{separator}{suffix}s"


def convert_french(
    text: str,
    target: str,
    masculine_words: set[str],
    feminine_words: set[str],
    is_word,
) -> str | None:
    """A French inclusive form in the target format, or None when `text` is
    not one: `enseignant.e.s` under `·` gives `enseignant·es`, `la/le` gives
    `la·le`, `un.e` gives `un·e`. `is_word(stem)` confirms a masculine noun
    or adjective, so `site.fr` or `p.ex` are left alone."""
    match = re.fullmatch(
        rf"({_FR_WORD})([·./])([{_FR}]+)(?:([·./])(s))?", text, flags=re.I
    )
    if match is None:
        return None

    stem, separator, rest, second, plural_s = match.groups()
    if second is not None and second != separator:
        return None

    lower_stem, lower_rest = stem.lower(), rest.lower()

    # An article pair (`la·le`) or an article with an ending (`un·e`).
    if second is None:
        words = {lower_stem, lower_rest}
        if words & masculine_words and words & feminine_words and len(words) == 2:
            return f"{stem}{target[0]}{rest}"
        if lower_stem in masculine_words and lower_stem + lower_rest in feminine_words:
            return f"{stem}{target[0]}{rest}"

    # A noun or adjective: masculine word, feminine suffix, maybe a plural.
    if second is not None:
        parts = (lower_rest, True) if lower_rest in FRENCH_FEMININE_SUFFIXES else None
    else:
        parts = split_french_ending(lower_rest)
    if parts is None or len(lower_stem) < 3 or not is_word(lower_stem):
        return None

    suffix, plural = parts
    # Keep the writer's case of the suffix (it is lowercase in practice).
    written_suffix = rest[: len(suffix)]

    return render_french(stem, written_suffix, plural, target)


# Articles a French doublet can start with. `les`, `des`, `aux` and `l'` serve
# both nouns, so the second one may leave it out (`les enseignants et
# enseignantes`); `le`/`la` and `un`/`une` have to be repeated.
FRENCH_DOUBLET_ARTICLES = {"le", "la", "l'", "l’", "les", "un", "une", "des", "aux"}
_FRENCH_SHARED_ARTICLES = {"les", "des", "aux", "l'", "l’"}


def french_doublet(
    tokens, index: int, conjunctions: set[str], articles_map: dict
) -> tuple[int | None, int, int | None, int] | None:
    """The token positions of a doublet starting at `index`, as (first article,
    first noun, second article, second noun) with None for a missing article:
    `les enseignants et les enseignantes`, `le directeur ou la directrice`,
    `enseignantes et enseignants`. Only the shape: whether the nouns are the
    two genders of one role is for the caller to look up."""

    def article(i: int) -> str | None:
        word = tokens[i].text.lower() if i < len(tokens) else ""
        return word if word in FRENCH_DOUBLET_ARTICLES else None

    first_article = index if article(index) else None
    if first_article is None and index > 0 and article(index - 1):
        # Checked from the article, where the doublet starts.
        return None
    first = index + (first_article is not None)
    if first + 2 >= len(tokens) or tokens[first + 1].text.lower() not in conjunctions:
        return None

    second_article = first + 2 if article(first + 2) else None
    second = first + 2 + (second_article is not None)
    if second >= len(tokens) or not tokens[second].is_alpha:
        return None
    if not tokens[first].is_alpha:
        return None

    one, other = (
        tokens[first_article].text.lower() if first_article is not None else None,
        tokens[second_article].text.lower() if second_article is not None else None,
    )
    if one is None and other is not None:
        return None
    if other is None and one is not None and one not in _FRENCH_SHARED_ARTICLES:
        return None
    if other is not None and other != one and articles_map.get(one) != other:
        return None

    return first_article, first, second_article, second
