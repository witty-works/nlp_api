"""Noun forms for the Inklusivum (de-e).

The Inklusivum is a fourth grammatical gender rather than a separator spliced
into a word, so its nouns are built from the masculine stem and then declined,
instead of being assembled from a male and a female surface form.

Rules follow the Verein für geschlechtsneutrales Deutsch e. V.:
  https://geschlechtsneutral.net/gesamtsystem/
  https://geschlechtsneutral.net/ausnahmeformen/
"""

from dataclasses import dataclass, field

from app.alternatives_engine.utils import add_german_prefix


@dataclass(frozen=True)
class Lexicon:
    """The word lists the noun rules consult.

    Kept together because they are only ever correct together: leaving one out
    silently changes which rule applies, which is how the same word once came
    out as "Gast" on its own and "Gaste" inside a compound.
    """

    exceptions: dict = field(default_factory=dict)
    neutral: frozenset = frozenset()

    @classmethod
    def from_static_rules(cls, static_rules: dict, lang) -> "Lexicon":
        rules = (static_rules or {}).get(lang, {})

        return cls(
            exceptions=rules.get("inklusivum_nouns") or {},
            neutral=frozenset(rules.get("inklusivum_neutral_nouns") or ()),
        )


UMLAUTS = {"ä": "a", "ö": "o", "ü": "u", "Ä": "A", "Ö": "O", "Ü": "U"}

# Only these two slots put an ending on the noun itself; every other
# distinction is carried by the article.
GENITIVE_SINGULAR = "sg_gen"
DATIVE_PLURAL = "pl_dat"

PLURAL_FORMS = ("pl_nom", "pl_acc", "pl_dat", "pl_gen")

# Declension columns carry number and case together; adjective endings only
# care about the case.
TARGET_FORM_CASES = {
    "sg_nom": "nominativ",
    "sg_acc": "akkusativ",
    "sg_gen": "genitiv",
    "sg_dat": "dativ",
    "pl_nom": "nominativ",
    "pl_acc": "akkusativ",
    "pl_gen": "genitiv",
    "pl_dat": "dativ",
}


def _without_umlauts(word: str) -> str:
    for umlaut, plain in UMLAUTS.items():
        word = word.replace(umlaut, plain)
    return word


def singular(masculine: str) -> str:
    """Schüler -> Schülere, Kollege -> Kollegere, Arzt -> Arzte.

    A masculine already ending in -e gains an -re rather than a second -e,
    which would be unpronounceable.
    """
    if masculine.endswith("e"):
        return masculine + "re"

    return masculine + "e"


# A productive suffix, and every noun formed with it is already neutral:
# Flüchtling, Liebling, Prüfling, Lehrling, Säugling, Zwilling and so on.
NEUTRAL_SUFFIXES = ("ling",)


def is_already_neutral(word: str, neutral_nouns: set | None = None) -> bool:
    """Whether the word needs no ending at all.

    These carry no gender to remove, so the Inklusivum leaves the word alone
    and changes only the article: "de Gast", not "de Gaste". Some of them do
    have a feminine in the lexicon, "Gästin" for instance, which is a real
    word but not a reason to derive a form the system does not use.
    """
    if not word:
        return False

    if word.endswith(NEUTRAL_SUFFIXES):
        return True

    return word in (neutral_nouns or set())


def _romance_stem(masculine: str, feminine: str) -> str | None:
    """Alumnus/Alumna, Ballerino/Ballerina and the like.

    These replace their ending rather than taking -in, so the ending goes and
    the Inklusivum -e takes its place: Alumne, Ballerine, Torere.
    """
    for ending in ("us", "o"):
        if not masculine.endswith(ending) or not feminine.endswith("a"):
            continue

        stem = masculine[: -len(ending)]
        if stem == feminine[:-1]:
            return stem

    return None


def _double_er_stem(masculine: str, feminine: str) -> str | None:
    """Wanderer/Wanderin, Zauberer/Zauberin.

    A handful of -er nouns end in -erer, where -in replaces the second -er
    instead of being appended. The Inklusivum is built from the shortest stem
    the two forms share, so Wandere rather than Wanderere.
    """
    if masculine.endswith("erer") and feminine == masculine[:-2] + "in":
        return masculine[:-2]

    return None


def stem(masculine: str, feminine: str) -> str:
    """The base the Inklusivum ending attaches to."""
    return (
        _romance_stem(masculine, feminine or "")
        or _double_er_stem(masculine, feminine or "")
        or masculine
    )


def plural(singular_form: str) -> str:
    """Schülere -> Schülerne, Studente -> Studenterne."""
    if singular_form.endswith("re"):
        return singular_form[:-1] + "ne"

    return singular_form + "rne"


def _umlauted_stem(masculine: str, feminine: str) -> str | None:
    """Return the feminine's stem when it differs only by an umlaut.

    Arzt/Ärztin and Koch/Köchin carry the umlaut into the Inklusivum plural
    but not into the singular, so the two stems are kept apart.
    """
    if not feminine.endswith("in"):
        return None

    stem = feminine[:-2]
    if stem == masculine:
        return None

    if _without_umlauts(stem) != _without_umlauts(masculine):
        return None

    return stem if stem != _without_umlauts(stem) else None


def apply_case(form: str, target_form: str | None) -> str:
    """Genitive singular takes -s, dative plural -n; the rest are unmarked."""
    if target_form == GENITIVE_SINGULAR:
        return form + "s"

    if target_form == DATIVE_PLURAL:
        return form + "n"

    return form


def is_substantivized_adjective(masculine: str, feminine: str) -> bool:
    """Whether a pair is an adjective used as a noun.

    Vorgesetzter/Vorgesetzte and Angestellter/Angestellte drop the masculine's
    final r rather than adding -in, which is adjective agreement rather than
    noun derivation and separates them cleanly from Lehrer/Lehrerin.
    """
    if not masculine or not feminine:
        return False

    return masculine.endswith("er") and feminine == masculine[:-1]


def substantivized_adjective(
    masculine: str,
    target_form: str | None = None,
    prefix: str = "",
    has_article: bool = True,
) -> str:
    """Decline an adjective used as a noun.

    These keep taking adjective endings in the Inklusivum, so "de Vorgesetzte"
    and "Vorgesetztey", never the noun ending that would give Vorgesetztere.
    """
    stem = masculine[:-2]

    if target_form in PLURAL_FORMS:
        # Plurals are ordinary German here, which is already gender neutral.
        form = stem + ("en" if has_article else "e")
    else:
        form = adjective(stem, TARGET_FORM_CASES.get(target_form), has_article)

    return add_german_prefix(form, prefix)


def noun(
    masculine: str,
    feminine: str,
    target_form: str | None = None,
    prefix: str = "",
    lexicon: Lexicon | None = None,
    has_article: bool = True,
) -> str | None:
    """Build the Inklusivum noun for a masculine/feminine pair.

    ``target_form`` is a German noun declension column (``sg_gen``,
    ``pl_dat``, ...) and selects number and case. ``exceptions`` maps a
    masculine base form to an explicit ``(singular, plural)`` pair for the
    words the regular rules cannot derive and the words that take no ending
    at all.
    """
    if not masculine:
        return None

    lexicon = lexicon or Lexicon()

    if is_already_neutral(masculine, lexicon.neutral):
        return add_german_prefix(masculine, prefix)

    is_plural = target_form in PLURAL_FORMS

    override = lexicon.exceptions.get(masculine)
    if override is not None:
        singular_form, plural_form = override
        form = plural_form if is_plural else singular_form
        return add_german_prefix(apply_case(form, target_form), prefix)

    if is_substantivized_adjective(masculine, feminine):
        return substantivized_adjective(masculine, target_form, prefix, has_article)

    singular_form = singular(stem(masculine, feminine))

    if is_plural:
        umlauted = _umlauted_stem(masculine, feminine or "")
        form = plural(singular(umlauted) if umlauted else singular_form)
    else:
        form = singular_form

    return add_german_prefix(apply_case(form, target_form), prefix)


# Shortest form the rules can produce is a two letter stem plus its ending.
MIN_STEM = 3


def base_form_candidates(word: str) -> list[str]:
    """Masculine base forms that ``word`` could be the Inklusivum of.

    Detection cannot be done on shape alone, because an Inklusivum noun looks
    like any other German noun ending in -e. This undoes the endings to
    produce candidates; the caller decides which of them is a real gendered
    person word by looking it up.

    Ordered most specific first, so a caller taking the first hit prefers the
    less ambiguous reading.
    """
    if not word or not word[0].isupper():
        return []

    candidates = []

    def add(candidate: str) -> None:
        if len(candidate) >= MIN_STEM and candidate not in candidates:
            candidates.append(candidate)

    for stem in _undeclined(word):
        for singular_form in _undo_plural(stem):
            for masculine in _undo_singular(singular_form):
                add(masculine)

    return candidates


def _undeclined(word: str) -> list[str]:
    """Undo the genitive singular -s and the dative plural -n."""
    stems = [word]

    if word.endswith("s"):
        stems.append(word[:-1])
    if word.endswith("nen"):
        stems.append(word[:-1])

    return stems


def _undo_plural(stem: str) -> list[str]:
    """Inklusivum singulars a stem could be the plural of, plus the stem."""
    forms = [stem]

    # Studenterne -> Studente
    if stem.endswith("rne"):
        forms.append(stem[:-3])

    # Schülerne -> Schülere
    if stem.endswith("ne"):
        forms.append(stem[:-2] + "e")

    return forms


# Unlike standard German the Inklusivum does not split weak from mixed: the
# endings after de, ein and jedey are the same. Only the absence of an article
# selects a different set, where -ey keeps the form apart from the feminine.
ADJECTIVE_ENDINGS_AFTER_ARTICLE = {
    "nominativ": "e",
    "akkusativ": "e",
    "genitiv": "en",
    "dativ": "en",
}
ADJECTIVE_ENDINGS_BARE = {
    "nominativ": "ey",
    "akkusativ": "ey",
    "genitiv": "ers",
    "dativ": "erm",
}


def adjective(stem: str, case: str | None = None, has_article: bool = True) -> str:
    """Decline an adjective stem.

    ``stem`` is the adjective without any ending, ``case`` a German case name
    as used in the article table. Plural adjectives are not handled here: the
    Inklusivum keeps the ordinary German plural, which is already neutral.
    """
    endings = ADJECTIVE_ENDINGS_AFTER_ARTICLE if has_article else ADJECTIVE_ENDINGS_BARE

    return stem + endings.get(case or "nominativ", endings["nominativ"])


# The possessive of "en". Both gendered stems map onto it.
POSSESSIVE_STEMS = ("sein", "ihr")
POSSESSIVE = "ens"


def possessive(form: str) -> str | None:
    """Swap a gendered possessive for the Inklusivum one.

    "seinem" and "ihrem" already agree with the noun they modify, so only the
    stem changes and the agreement is carried over for free: ens, ense, ensem,
    ensen. Returns None when the word is not a possessive.
    """
    lowered = form.lower()

    for stem in POSSESSIVE_STEMS:
        if lowered.startswith(stem):
            return POSSESSIVE + lowered[len(stem) :]

    return None


def possessive_pair(tilde_word: str) -> str | None:
    """Inklusivum form for a gendered possessive pair such as "ihrem~seinem".

    Both sides modify the same noun, so they have to land on the same form.
    Requiring that is also the check that this really is such a pair.
    """
    parts = tilde_word.split("~")
    if len(parts) != 2:
        return None

    forms = [possessive(part) for part in parts]
    if forms[0] is None or forms[0] != forms[1]:
        return None

    return forms[0]


# Used without a noun, the ein-paradigm takes -ey where the article form is
# bare: "nicht jedey mag das", "kennt das einey von euch?". The article stays
# "ein", so the two cannot share a table.
PRONOMINAL = {
    "nominativ": "einey",
    "akkusativ": "einey",
    "genitiv": "einers",
    "dativ": "einerm",
}


def pronominal(case: str | None = None) -> str:
    """The ein-paradigm standing on its own, with no noun after it."""
    return PRONOMINAL.get(case or "nominativ", PRONOMINAL["nominativ"])


# Endings "ens" takes, agreeing with the noun it modifies.
POSSESSIVE_ENDINGS = ("", "e", "em", "en", "er", "es", "ers", "erm")


def is_possessive_form(word: str) -> bool:
    """Whether the word is a declined form of the possessive "ens"."""
    lowered = word.lower()

    if not lowered.startswith(POSSESSIVE):
        return False

    return lowered[len(POSSESSIVE) :] in POSSESSIVE_ENDINGS


# The article-less adjective endings. -ers is left out on purpose: it is a
# perfectly ordinary word ending ("anders", "besonders"), where these two are
# effectively unique to this system.
DISTINCTIVE_ADJECTIVE_ENDINGS = ("ey", "erm")


def is_adjective_form(word: str) -> bool:
    """Whether the word carries an ending only the Inklusivum uses.

    Shape is enough here, unlike for nouns, because these endings do not
    otherwise occur. Used to keep the spell checker off them.
    """
    lowered = word.lower()

    return len(lowered) > 4 and lowered.endswith(DISTINCTIVE_ADJECTIVE_ENDINGS)


def adjective_stem(tilde_word: str) -> str:
    """Strip the gendered ending off a tilde marked adjective.

    The rules write these two ways round, with the tilde marking where the
    gendered part starts: qualifiziert~e and qualifizierte~r both stem to
    qualifiziert.
    """
    before, _, after = tilde_word.partition("~")

    if after == "r" and before.endswith("e"):
        return before[:-1]

    return before


ALL_TARGET_FORMS = ("sg_nom", "sg_gen", "pl_nom", "pl_dat")


def is_form_of(
    word: str, masculine: str, feminine: str, lexicon: Lexicon | None = None
) -> bool:
    """Whether ``word`` is an Inklusivum form of this masculine/feminine pair.

    Candidates recovered from the surface alone are ambiguous, so this runs
    the forward rules and requires an exact match rather than trusting the
    reversal.
    """
    return any(
        noun(masculine, feminine, target_form, "", lexicon) == word
        for target_form in ALL_TARGET_FORMS
    )


def _undo_singular(singular_form: str) -> list[str]:
    """Masculines a singular could have been built from.

    Both readings are returned because they are genuinely ambiguous on shape:
    Lehrere undoes to Lehrer, but by the same letters Kollegere undoes to
    Kollege.
    """
    forms = []

    if singular_form.endswith("re"):
        forms.append(singular_form[:-2])
    if singular_form.endswith("e"):
        forms.append(singular_form[:-1])

    return forms
