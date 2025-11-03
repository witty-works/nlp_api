import emoji
import re
from app.models import Config, LangType


def is_gender_star_ending(text: str) -> bool | re.Match:
    for regexp in Config._gendereddenom_ending.default:
        match = re.search(Config._gendereddenom_ending.default[regexp], text)
        if match:
            return match

    return False


def remove_gender_ending(text: str) -> str:
    if text[0].islower():
        return text

    if text.endswith("-"):
        ending = "s-" if text.endswith("s-") else "-"
        text = text.removesuffix(ending)

    match = is_gender_star_ending(text)
    if match:
        text = match[1] + match[2]

    return text


def upperfirst(x: str) -> str:
    """Capitalize the first character of a string.

    Args:
        x: Input string

    Returns:
        String with first character uppercased
    """
    return x[0].upper() + x[1:] if x else x.capitalize()


def find_common_prefix(
    text1: str, text2: str, lower: bool = True, ignore_umlauts: bool = True
) -> str:
    """Find the common prefix between two strings.

    Args:
        text1: First string
        text2: Second string to compare
        lower: If True, perform case-insensitive comparison
        ignore_umlauts: If True, normalize umlauts before comparison

    Returns:
        Common prefix string, or empty string if no common prefix
    """
    # Quick check: if umlaut counts don't match, no valid prefix
    if text1.lower().count("ä") != text2.lower().count("ä"):
        return ""

    prefix = text1
    if ignore_umlauts:
        prefix = prefix.replace("ä", "a").replace("ö", "o").replace("ü", "u")
    if lower:
        prefix = prefix.lower()

    normalized_text2 = text2
    if ignore_umlauts:
        normalized_text2 = (
            normalized_text2.replace("ä", "a").replace("ö", "o").replace("ü", "u")
        )

    # Shrink prefix until it matches or becomes empty
    while prefix and not normalized_text2.startswith(prefix):
        prefix = prefix[:-1]

    return prefix


def find_matching_form(
    forms: dict | None, text: str, is_singular: bool | None = None
) -> str | None:
    if forms is None:
        return forms

    text_lower = text.lower()

    for form in forms:
        if is_singular is not None:
            if is_singular:
                if form.startswith("pl_"):
                    continue
            elif form.startswith("sg_"):
                continue

        if isinstance(forms[form], str) and forms[form].lower() == text_lower:
            return form.removesuffix("_2")

    return None


def check_word_case(text: str, is_first_upper: bool | None = None) -> bool:
    """Check if all words in hyphenated text follow proper casing rules.

    Args:
        text: Hyphenated or simple text to check
        is_first_upper: If set, enforces first character case requirement

    Returns:
        True if casing is valid, False otherwise
    """
    if text.endswith("-"):
        return False

    words = text.split("-")
    for word in words:
        if not word:  # Skip empty strings
            continue

        if is_first_upper is not None:
            if word[0].isupper() != is_first_upper:
                return False
            word = word[1:]

        if not word.islower():
            return False

    return True


def get_target_declension_form(target_result: dict, target_form: str) -> str | None:
    """Get a specific declension form from a result dictionary.

    Args:
        target_result: Dictionary containing declension forms
        target_form: The form key to retrieve

    Returns:
        The requested form, base_form as fallback, or None if not found
    """
    if target_result is None or target_form not in target_result:
        return None

    form_value = target_result[target_form]
    return form_value if form_value else target_result.get("base_form")


def is_valid_text(lang: LangType, text: str) -> bool:
    if text == "(":
        return True

    match (lang):
        case LangType.EN:
            if text.lower() in ["a", "i", "o"]:
                return True
        case LangType.FR:
            if text.lower() in ["a", "à", "y"]:
                return True

    if len(text) <= 1:
        return False

    return any(c.isalnum() for c in text)


def is_addon_enabled(addon: str, addons: None | list[str]) -> bool:
    """Check if an addon is enabled.

    Args:
        addon: The addon name to check
        addons: List of enabled addons, or None (meaning all enabled)

    Returns:
        True if addon is enabled or addons list is None
    """
    return addons is None or addon in addons


def utf16len(c: str) -> int:
    """Returns the length of the single character 'c'
    in UTF-16 code units."""
    return 1 if ord(c) < 65536 else 2


def utf16_offsets(text: str) -> dict | bool:
    """Calculate UTF-16 character offsets for text containing special characters.

    Args:
        text: Input text that may contain emojis or multi-byte characters

    Returns:
        Dictionary with offset mappings if special chars exist, False otherwise
    """
    utf16offset = 0
    offsets = {
        "chars": [],
        "utf16_chars": {},
    }

    for counter, char in enumerate(text):
        current_offset = counter + utf16offset
        offsets["chars"].append(current_offset)
        offsets["utf16_chars"][current_offset] = counter

        if utf16len(char) > 1 or emoji.is_emoji(char):
            utf16offset += 1

    # Add final offset
    final_offset = len(text) + utf16offset
    offsets["chars"].append(final_offset)
    offsets["utf16_chars"][final_offset] = len(text)

    return offsets if utf16offset else False
