"""Formatting helpers for gendered/inclusive alternatives."""

from app.models import LangType, INKLUSIVUM_SEPARATOR
from app.helper import upperfirst, find_common_prefix
from app.alternatives_engine import inklusivum


def inclusive_alternative(
    static_rules: dict,
    lang: LangType,
    male_form: str,
    female_form: str,
    prefix: str,
    separator: str,
    noun_separator: str,
    separate_gender_plural: bool,
):
    if lang == LangType.DE:
        # Everything below assembles a word around a separator, which the
        # Inklusivum does not have. The main path builds these in
        # alternatives.py, where the declensions are available; callers that
        # only hold surface forms, such as the rephrase endpoint, land here.
        if separator == INKLUSIVUM_SEPARATOR:
            return inklusivum.singular(male_form)

        if male_form.lower() in static_rules[lang]["masculine_articles"]:
            return female_form + separator + male_form

        short_gender_star = True
        common_prefix = (
            ""
            if male_form.endswith("mann")
            else find_common_prefix(male_form, female_form, False, False)
        )
        if len(male_form) - len(common_prefix) > 2:
            common_prefix = female_form
            suffix = _add_german_prefix(male_form, prefix)
            short_gender_star = False
        elif len(female_form) >= len(male_form):
            # Mitarbeiterin + Mitarbeiter = Mitarbeiter
            suffix = female_form[len(common_prefix) :]
        else:
            # Vorgesetze + Vorgesetzter = Vorgesetze
            suffix = male_form[len(common_prefix) :]

        temp_separator = noun_separator
        # In
        if separator != noun_separator:
            if short_gender_star:
                suffix = upperfirst(suffix)
            else:
                temp_separator = "/"

        return _add_german_prefix(common_prefix + temp_separator + suffix, prefix)

    if lang == LangType.FR:
        male_form_lower = male_form.lower()
        if male_form_lower in static_rules[lang]["masculine_articles"]:
            inclusive_form = static_rules[lang]["masculine_articles"][male_form_lower]
            if male_form != male_form_lower:
                inclusive_form = upperfirst(inclusive_form)
            return inclusive_form

        common_prefix = find_common_prefix(male_form, female_form, False, False)
        # Il est un poète
        if len(common_prefix) < 3:
            return prefix + male_form + separator + female_form.lower()

        if len(female_form) >= len(male_form):
            suffix = female_form[len(common_prefix) :]
            gender_prefix = male_form
        else:
            suffix = male_form[len(common_prefix) :]
            gender_prefix = female_form

        # expérimentés / expérimentées => expérimenté·es
        if gender_prefix.endswith("s"):
            gender_prefix = gender_prefix[0:-1]

        if separate_gender_plural and suffix.endswith("s"):
            suffix = suffix[0:-1] + separator + "s"

        return prefix + gender_prefix + separator + suffix

    return None


def _add_german_prefix(word: str, prefix: str) -> str:
    if len(prefix) == 0 or word.startswith(prefix):
        return word

    if not word.startswith("-") and not prefix.endswith("-"):
        word = word[0].lower() + word[1:]

    return prefix + word
