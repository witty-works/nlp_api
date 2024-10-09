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


def upperfirst(x: str):
    return x[0].upper() + x[1:]


def find_common_prefix(
    text1: str, text2: str, lower: bool = True, ignore_umlauts: bool = True
) -> str:
    prefix = text1

    if text1.lower().count("ä") != text2.lower().count("ä"):
        return ""

    if ignore_umlauts:
        prefix = prefix.replace("ä", "a").replace("ö", "o").replace("ü", "u")
    if lower:
        prefix = prefix.lower()

    if ignore_umlauts:
        text2 = text2.replace("ä", "a").replace("ö", "o").replace("ü", "u")

    while text2[: len(prefix)] != prefix and prefix:
        prefix = prefix[: len(prefix) - 1]
        if not prefix:
            break

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


def check_word_case(text: str, is_first_upper: bool | None = None):
    if text.endswith("-"):
        return False

    words = text.split("-")
    for word in words:
        if len(word) == 0:
            continue

        if is_first_upper is not None:
            if word[0].isupper() != is_first_upper:
                return False

            word = word[1:]

        if not word.islower():
            return False

    return True


def get_target_declension_form(target_result: dict, target_form: str):
    if target_result is None or target_form not in target_result:
        return None

    if target_result[target_form] is None or target_result[target_form] == "":
        return target_result["base_form"]

    return target_result[target_form]


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


def is_addon_enabled(addon: str, addons: None | list[str]):
    return addons is None or addon in addons


def utf16len(c: str) -> int:
    """Returns the length of the single character 'c'
    in UTF-16 code units."""
    return 1 if ord(c) < 65536 else 2


def utf16_offsets(text: str) -> dict:
    utf16offset = 0

    offsets = {
        "chars": [],
        "utf16_chars": {},
    }

    counter = 0
    for char in [*text]:
        offsets["chars"].append(counter + utf16offset)
        offsets["utf16_chars"][counter + utf16offset] = counter

        counter += 1

        if utf16len(char) > 1 or emoji.is_emoji(char):
            utf16offset += 1

    offsets["chars"].append(counter + utf16offset)
    offsets["utf16_chars"][counter + utf16offset] = counter

    return offsets if utf16offset else False
