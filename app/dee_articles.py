"""Helpers to generate De-e (Inklusivum) article forms.

This module contains a small, dependency-free generator used by the
article loader and by unit tests so tests can run without pandas.
"""

from typing import Optional


POSSESSIVE_ROOT_MAP = {
    "unser": "unse",
    "uns": "unse",
    "euer": "eue",
    "eur": "eue",
    "mein": "mein",
    "dein": "dein",
    "sein": "sein",
    "ihr": "ihr",
}


def _normalize(token: Optional[str]) -> str:
    return (token or "").strip().lower()


def generate_dee_inclusive(
    form: str, masculine: Optional[str], feminine: Optional[str]
) -> str:
    """Return an inclusive De-e article string for given CSV fields.

    Rules implemented (heuristic, following user spec):
    - base nominative: 'de'
    - genitive: base + 'rs' -> 'ders'
    - dative: base + 'rm' -> 'derm'
    - 'ein' paradigm: base 'ein' with 'einers'/'einerm'
    - 'jeder' paradigm: base 'jedey' with 'jeders'/'jederm'
    - possessives ending with 'r' -> replace trailing 'r' with 'e' (e.g. 'unser' -> 'unse')
    - contractions: if masculine or feminine contains 'zum'/'zur' and form is dative,
      produce 'zurm' as inclusive contraction.
    """
    masc = _normalize(masculine)
    fem = _normalize(feminine)
    form_l = _normalize(form)

    # detect pronoun rows (e.g. er/sie/es) and prefer the pronoun-style base 'en'
    PRONOUN_SET = {"er", "sie", "es", "ihn", "ihm", "ihr", "seiner", "seine"}
    if masc in PRONOUN_SET or fem in PRONOUN_SET:
        if "gen" in form_l:
            return "enser"
        if "dat" in form_l:
            return "em"
        return "en"

    # contraction handling: 'zum' / 'zur' -> 'zurm' for dative
    if "dat" in form_l and ("zum" in masc or "zur" in fem):
        return "zurm"

    # determine base
    if masc.startswith("ein"):
        base = "ein"
    elif masc.startswith("jed") or fem.startswith("jede"):
        base = "jedey"
    else:
        base = None

    if base is None:
        # check possessive roots
        for root, mapped in POSSESSIVE_ROOT_MAP.items():
            if masc.startswith(root) or fem.startswith(root):
                base = mapped
                break

    if base is None:
        base = "de"

    # special case: jedey -> jeders/jederm (not naive append)
    if base == "jedey":
        stem = base[:-2]
        if "gen" in form_l:
            return stem + "ers"
        if "dat" in form_l:
            return stem + "erm"

    # special-case: 'ein' paradigm wants 'einers'/'einerm' not 'einrs'/'einrm'
    if base == "ein":
        if "gen" in form_l:
            return base + "ers"
        if "dat" in form_l:
            return base + "erm"

    if "gen" in form_l:
        return base + "rs"
    if "dat" in form_l:
        return base + "rm"

    return base
