"""Formatting helpers for gendered/inclusive alternatives."""

from app.models import LangType
from app.helper import upperfirst, find_common_prefix


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
        # De-e / Inklusivum (special inclusive system): handled via sentinel separator 'DEE'
        if separator == "DEE" or noun_separator == "DEE":
            # Build De-e inclusive form: prefer female stem without '-in', fallback to male stem
            def _dee_stem(m, f):
                if f and f.endswith("in"):
                    return f[:-2]
                if m and m.endswith("er"):
                    return m[:-2]
                # fallback to common prefix or male form
                pref = find_common_prefix(m, f, False, False)
                return pref if len(pref) >= 3 else m

            stem = _dee_stem(male_form, female_form)
            if stem is None:
                return None

            inclusive = stem
            if not inclusive.endswith("e"):
                inclusive = inclusive + "e"

            # return singular De-e inclusive form with proper prefix handling
            return _add_german_prefix(inclusive, prefix)

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
