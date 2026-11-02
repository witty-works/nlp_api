"""The inclusive-language guidance Witty GPT puts in front of a model, before
the model has answered. Kept free of the app's other modules: app.prompt uses
it for its default system prompt."""

import copy

from app.models import (
    Config,
    FrenchGenderSeparatorType,
    GermanGenderEndingType,
    LangWithAutoType,
)

BASE_GUIDANCE = """You are an expert in inclusive language.
Keep gender equality in mind and avoid language that is needlessly gendered (f.e. use truly gender neutral nouns, avoid pronouns).
Do not make biased assumptions.
Do not rely on social stereotypes.
Do not use derogatory language even as a joke.
Avoid jargon terms, specially sports or military terms.

Specifically make use of communal and inclusive language."""

# For a caller that needs the text alone, as /v1.0/write does. A gateway's own
# conversation would only be disturbed by it.
BARE_TEXT_INSTRUCTION = 'Follow instructions without mentioning them in your response. Specifically do not add phrases like "Greetings", "Here is .." or "Sure .." to the beginning of your response.'

# The Inklusivum has no line: models cannot write it reliably, and the review of
# the answer brings it in where it applies.
GERMAN_EXAMPLES = {
    GermanGenderEndingType.SLASH: "Lehrer/in",
    GermanGenderEndingType.SLASH_DASH: "Lehrer/-in",
    GermanGenderEndingType.UNDERSCORE: "Lehrer_in",
    GermanGenderEndingType.STAR: "Lehrer*in",
    GermanGenderEndingType.COLON: "Lehrer:in",
    GermanGenderEndingType.PARENTHESIS_DASH: "Lehrer(-in)",
    GermanGenderEndingType.PARENTHESIS: "Lehrer(in)",
    GermanGenderEndingType.CAPITAL_LETTER: "LehrerIn",
}

FRENCH_EXAMPLES = {
    FrenchGenderSeparatorType.POINT_MEDIAN: "étudiant·e",
    FrenchGenderSeparatorType.POINT_MEDIAN_S: "étudiant·e·s",
    FrenchGenderSeparatorType.POINT: "étudiant.e",
    FrenchGenderSeparatorType.POINT_S: "étudiant.e.s",
    FrenchGenderSeparatorType.SLASH: "étudiant/e",
    FrenchGenderSeparatorType.SLASH_S: "étudiant/e/s",
}


def guidance(config: Config, lang: LangWithAutoType | None = None) -> str:
    """The system prompt text for a request, with the gender forms `config`
    asks for. Before the model has answered its language is rarely known, so
    without `lang` both the German and the French line are added."""
    known = None if lang in (None, LangWithAutoType.AUTO) else lang.value[0:2]

    lines = [BASE_GUIDANCE]

    german = GERMAN_EXAMPLES.get(config.german_gender_ending)
    if german is not None and known in (None, "de"):
        lines.append(
            f'When writing German, form gender-inclusive person nouns like "{german}".'
        )

    french = FRENCH_EXAMPLES.get(config.french_gender_separator)
    if french is not None and known in (None, "fr"):
        lines.append(
            f'When writing French, form gender-inclusive person nouns like "{french}".'
        )

    return "\n".join(lines)


def merge_guidance(messages: list[dict], text: str) -> list[dict]:
    """`messages` with `text` added to the system message, or in a new one
    ahead of them. The caller's messages are left as they were."""
    if not messages or messages[0].get("role") != "system":
        return [{"role": "system", "content": text}, *messages]

    system = copy.deepcopy(messages[0])
    content = system.get("content")
    if isinstance(content, list):
        content.append({"type": "text", "text": text})
    elif content:
        system["content"] = f"{content}\n\n{text}"
    else:
        system["content"] = text

    return [system, *messages[1:]]

