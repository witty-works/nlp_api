"""Noun forms for the Inklusivum (de-e).

The Inklusivum is a fourth grammatical gender rather than a separator spliced
into a word, so its nouns are built from the masculine stem and then declined,
instead of being assembled from a male and a female surface form.

Rules follow the Verein für geschlechtsneutrales Deutsch e. V.:
  https://geschlechtsneutral.net/gesamtsystem/
  https://geschlechtsneutral.net/ausnahmeformen/
"""

from app.alternatives_engine.utils import add_german_prefix

UMLAUTS = {"ä": "a", "ö": "o", "ü": "u", "Ä": "A", "Ö": "O", "Ü": "U"}

# Only these two slots put an ending on the noun itself; every other
# distinction is carried by the article.
GENITIVE_SINGULAR = "sg_gen"
DATIVE_PLURAL = "pl_dat"

PLURAL_FORMS = ("pl_nom", "pl_acc", "pl_dat", "pl_gen")


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


def noun(
    masculine: str,
    feminine: str,
    target_form: str | None = None,
    prefix: str = "",
    exceptions: dict | None = None,
) -> str | None:
    """Build the Inklusivum noun for a masculine/feminine pair.

    ``target_form`` is a German noun declension column (``sg_gen``,
    ``pl_dat``, ...) and selects number and case. ``exceptions`` maps a
    masculine base form to an explicit ``(singular, plural)`` pair for the
    words the regular rules cannot derive.
    """
    if not masculine:
        return None

    is_plural = target_form in PLURAL_FORMS

    override = (exceptions or {}).get(masculine)
    if override is not None:
        singular_form, plural_form = override
        form = plural_form if is_plural else singular_form
        return add_german_prefix(apply_case(form, target_form), prefix)

    singular_form = singular(masculine)

    if is_plural:
        umlauted = _umlauted_stem(masculine, feminine or "")
        form = plural(singular(umlauted) if umlauted else singular_form)
    else:
        form = singular_form

    return add_german_prefix(apply_case(form, target_form), prefix)
