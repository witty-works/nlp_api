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
from dataclasses import dataclass

from app.categories import is_sub_category_enabled
from app.helper import from_utf16
from app.models import (
    GENDER_ENDING_PARTS,
    Config,
    GermanGenderEndingType as Ending,
    LangType,
)


@dataclass(frozen=True)
class FormatSpec:
    """How one separator format writes a gendered form. Everything else about
    the formats (the tables below, the mismatch rules) is derived from these,
    so a format is described in one place."""

    # What joins a noun and its ending (`Lehrer*innen`); None where the format
    # marks it otherwise (Binnen-I, brackets).
    noun_separator: str | None
    # What joins an article or pronoun pair: the infix formats use their own
    # separator, the others a slash (Die/der LehrerIn, die/der Lehrer(in)).
    pair_separator: str
    # Whether a compound with the marker inside stays one token
    # (`Mitarbeiter*innengespräch`), so it can be read.
    compounds_in_one_token: bool
    # How the tokenizer splits an article pair in this format, as a rule's
    # word_types: a plain slash makes three tokens (`die / der`).
    article_word_types: tuple


FORMATS = {
    Ending.STAR: FormatSpec("*", "*", True, (None, None, "*")),
    Ending.UNDERSCORE: FormatSpec("_", "_", True, (None, None, "_")),
    Ending.COLON: FormatSpec(":", ":", True, (None, None, ":")),
    Ending.SLASH: FormatSpec("/", "/", False, (-1, 2, "/")),
    Ending.SLASH_DASH: FormatSpec("/-", "/", False, (None, None, "/")),
    Ending.CAPITAL_LETTER: FormatSpec(None, "/", False, (None, None, "I")),
    Ending.PARENTHESIS: FormatSpec(None, "/", False, (-1, 4, "(")),
    Ending.PARENTHESIS_DASH: FormatSpec(None, "/", False, (-1, 2, ")")),
}

NOUN_SEPARATORS = {
    ending: spec.noun_separator
    for ending, spec in FORMATS.items()
    if spec.noun_separator is not None
}
PAIR_SEPARATORS = {ending: spec.pair_separator for ending, spec in FORMATS.items()}

_ENDING_PREFIX = re.compile(r"^(?:/-|[*_:/]|\(-?)")
_GENDER_PART = re.compile(rf"^({'|'.join(GENDER_ENDING_PARTS)})(.*)$", re.S)

# Compounds with the marker inside, for the formats that keep them in one
# token: `Mitarbeiter*innengespräch`, `Lehrer:innen-Team`.
COMPOUND_PATTERNS = {
    ending: re.compile(
        rf"^[A-ZÄÖÜ][a-zäöüß]+{re.escape(spec.noun_separator)}innen"
        r"(?:[a-zäöüß]+|-\w[\w-]*)$"
    )
    for ending, spec in FORMATS.items()
    if spec.compounds_in_one_token
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
NOUN_GENDER_ENDINGS = frozenset(GENDER_ENDING_PARTS)
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


# What a mismatch rule reads (set as `rule.form_kind` where the rules are
# built): a noun ending, an article or pronoun pair, a compound.
FORM_NOUN = "noun"
FORM_ARTICLE = "article"
FORM_COMPOUND = "compound"


def form_span(
    rule,
    tokens,
    token_index: int,
    check_text: str,
    text: str,
    start: int,
    whole_word: bool,
) -> tuple[str, int, int]:
    """The written form a mismatch rule matched, where it starts, and its
    first token. A form the tokenizer split (`die / der`, `jede ( r )`) starts
    at the rule's first token; otherwise it is the match, or with
    `whole_word` the whole token (the Inklusivum replaces the word, a
    separator format only the ending)."""
    offset = rule.word_types[0] if rule.word_types else None
    if offset is not None and offset < 0 and token_index + offset >= 0:
        first = token_index + offset
        return check_text, tokens[first].idx, first
    if whole_word:
        return tokens[token_index].text, tokens[token_index].idx, token_index

    return text, start, token_index


# The `bulk` value of the alerts that make up the gender format switch, and
# the subcategory of those that are a form written in another format.
BULK_GENDER_FORMAT = "gender_format"
MISMATCH_SUBCATEGORY = "gendered_denominations_ending_advanced"


def format_switch_enabled(config: Config) -> bool:
    """Whether a check with this config reports forms written in another
    format (and so can switch the text): inclusive roles, and the mismatch
    subcategory enabled."""
    return Config.gendered_roles_format_inclusive(
        config.gendered_roles_format
    ) and is_sub_category_enabled(config.disabled_categories, MISMATCH_SUBCATEGORY)


def mark_bulk(result, index: int) -> bool:
    """Put `result` into the gender format switch, applying its alternative
    at `index`. Only where that alternative exists: cleaning up alternatives
    (duplicates of the text, the maximum count) may have dropped it, and an
    index pointing at nothing would break a client applying the switch."""
    alternatives = result.alternatives or []
    if not 0 <= index < len(alternatives) or not alternatives[index].text:
        return False

    result.bulk = BULK_GENDER_FORMAT
    result.bulk_alternative = index

    return True


def bulk_actions(lang: str, config: Config) -> list[str]:
    """The `bulk` groups a check in this language with this config can return:
    the gender format switch for German (any format, the Inklusivum too) and
    French, under the same conditions the rules produce its alerts."""
    if lang in (LangType.DE, LangType.FR) and format_switch_enabled(config):
        return [BULK_GENDER_FORMAT]

    return []


# A masculine right before a coordinated feminine is the first half of a pair
# formula the rules did not recognise, most often because of a typo in the
# second half (`Schüler und Schüllerinnen`): gendering the first half alone
# would leave `Schüler:innen und Schüllerinnen`.
# The words that join a pair formula (`Schüler und Schülerinnen`) or two
# coordinated nouns (`den Lehrer*innen und Kolleg*innen`).
GERMAN_CONJUNCTIONS = ("und", "oder", "sowie", "bzw.", "&")
_PAIR_TAIL = re.compile(
    r"\s+(?:"
    + "|".join(re.escape(word) for word in GERMAN_CONJUNCTIONS)
    + r")\s+[\w-]*?in(?:nen)?\b"
)
_FEMININE_END = re.compile(r"in(?:nen)?$")

# Roles written in the generic masculine: job titles, functions, leadership.
# Address forms (`Frau Meier`), pronouns and identity terms name a particular
# person and stay one-by-one.
_ROLE_SUBCATEGORIES = {"titles", "function", "leadership"}


def mark_masculines_for_bulk(
    results: list,
    text: str,
    lang: str = LangType.DE,
    inklusivum_words: set[str] = frozenset(),
    offsets: dict | bool = False,
) -> None:
    """Add generic masculines and pair formulas to the gender format switch.

    Every role alert offering the gender-inclusive form in the configured
    format (`Der Lehrer` -> `Die:der Lehrer:in`, `Schüler und Schülerinnen` ->
    `Schüler:innen`) is marked with `bulk_alternative` pointing at it, so
    "switch the gender format" also genders what was written in the generic
    masculine. Left out: feminine forms (`Die Lehrerin`, often a particular
    woman), a masculine that starts an unrecognised pair formula, anything
    overlapping an alert already in the switch, and Inklusivum nouns
    (`inklusivum_words`, e.g. `den Schülernen` read as `Schülern`): switching
    out of the Inklusivum is not supported, and converting only those would
    leave a half-switched text.
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
            words = result.text.split()
            if words and _FEMININE_END.search(words[-1]):
                continue
            # Right after this alert, not anywhere in the text: one
            # unrecognised pair must not keep every other alert for the same
            # word out of the switch.
            if _PAIR_TAIL.match(text, from_utf16(offsets, result.end)):
                continue
        if any(start < result.end and result.start < end for start, end in taken):
            continue
        if inklusivum_words.intersection(result.text.split()):
            continue

        if mark_bulk(result, index):
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


# --- Inklusivum -------------------------------------------------------------
#
# Switching into the Inklusivum (`de-e`) is not a separator swap: articles
# come from the article table (`die*der` -> `de`), nouns from the Inklusivum
# generator, which needs number (from the ending) and case. Only the genitive
# singular (-s) and the dative plural (-n) are marked, so that is what the case
# has to decide.

_MORPH_CASES = {
    "Nom": "nominativ",
    "Acc": "akkusativ",
    "Dat": "dativ",
    "Gen": "genitiv",
}


def inklusivum_pair(form: str, articles: dict) -> tuple[str, str] | None:
    """A separator pair in the Inklusivum, with the case the table gives it:
    `die*der` -> (`de`, `nominativ`), `Jede/r` -> (`Jedey`, `nominativ`)."""
    parts = split_form(form)
    if parts is None:
        return None

    found = articles.get(tuple(sorted(part.lower() for part in parts)))
    if found is None:
        return None

    inklusivum, case = found
    if form[:1].isupper():
        inklusivum = inklusivum[:1].upper() + inklusivum[1:]

    return inklusivum, case


def inklusivum_target_form(
    tokens, stem: int, plural: bool, articles: dict
) -> str | None:
    """The declension column for a noun switched into the Inklusivum, from the
    article before it or spaCy's case for it; None when neither says."""
    case = None
    if stem > 0:
        before = tokens[stem - 1]
        written = before.text
        if stem > 2 and before.text.isalpha() and tokens[stem - 2].text == "/":
            written = tokens[stem - 3].text + "/" + before.text
        paired = inklusivum_pair(written, articles)
        if paired is not None:
            case = paired[1]
        elif before.text.lower() == "des":
            case = "genitiv"
        elif before.text.lower() == "den" and plural:
            case = "dativ"
        elif before.text.lower() in GERMAN_CONJUNCTIONS and stem >= 2:
            # `den Lehrer*innen und Kolleg*innen`: the second of two
            # coordinated nouns takes the first one's case. The first form
            # may be split into tokens (`Lehrer(innen)`, `Lehrer/-innen`),
            # written without spaces: its stem is where they start.
            first = stem - 2
            while first > 0 and not tokens[first - 1].whitespace_:
                first -= 1
            return inklusivum_target_form(tokens, first, plural, articles)

    if case is None:
        morph = tokens[stem].morph.get("Case")
        case = _MORPH_CASES.get(morph[0]) if morph else None
    if case is None:
        return None

    if plural:
        return "pl_dat" if case == "dativ" else "pl_nom"

    return "sg_gen" if case == "genitiv" else "sg_nom"
