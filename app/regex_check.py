from app.models import Config, Client, LangType, Rule, Alternative, ResultOut, Language
from app.categories import is_sub_category_enabled
from app.helper import upperfirst
from app.nouns import Nouns
from app.settings import Settings
from spacy.tokens import Doc
import re
from copy import deepcopy
from logging import Logger


class RegexCheck:
    settings: Settings
    logger: Logger
    static_rules: dict
    nouns: Nouns

    def __init__(
        self, settings: Settings, logger: Logger, static_rules: dict, nouns: Nouns
    ):
        self.settings = settings
        self.logger = logger
        self.static_rules = static_rules
        self.nouns = nouns

    async def handle(
        self,
        config: Config,
        client: Client,
        language: Language,
        full_text: str,
        token_index: int,
        tokens: Doc,
        offsets: dict,
        list_full: list,
        rules: list[Rule],
        check_case=None,
    ) -> list:
        token = tokens[token_index]

        for rule in rules:
            subcategory = is_sub_category_enabled(
                config.disabled_categories, rule.subcategories
            )
            if not subcategory:
                continue

            connector_string = rule.word_types[-1]
            start = token.idx

            # run regex on exactly the token
            if rule.word_types[0] is None:
                text = check_text = token.text
                if connector_string not in token.text:
                    continue

                start_token = token_index
            else:
                try:
                    text = check_text = ""
                    start_token = rule.word_types[0] + token_index
                    max_end_token = rule.word_types[1] + token_index

                    if start_token == max_end_token:
                        check_text = token.text
                        connector_string_start = check_text.find(connector_string)
                        if connector_string_start == -1:
                            continue

                        text = check_text[connector_string_start:]
                        start += connector_string_start
                    else:
                        multi_part = max_end_token - start_token > 1
                        # "1,2,#" => "#forever"
                        if not multi_part:
                            if token.text != connector_string:
                                continue

                            text = check_text = connector_string
                        elif (
                            start_token + 1 >= len(tokens)
                            or tokens[start_token + 1].text != connector_string
                        ):
                            continue

                    while start_token < max_end_token:
                        offset_token = tokens[start_token]

                        check_text += offset_token.text
                        if start_token >= token_index:
                            text += offset_token.text

                        if offset_token.whitespace_ != "":
                            break

                        start_token += 1
                        if tokens[start_token].text != connector_string:
                            break

                        check_text += connector_string
                        if start_token >= token_index:
                            text += connector_string

                        if connector_string == "(":
                            connector_string = ")"

                        if (
                            connector_string == ")"
                            and tokens[start_token].text == connector_string
                        ):
                            break

                        start_token += 1
                except IndexError:
                    pass

            # handle "Noch besser x/f/m."
            text = text.rstrip(".")
            check_text = check_text.rstrip(".")

            if text == "" or not re.search(rule.lemma, check_text):
                continue

            if connector_string == "I":
                check_text = upperfirst(check_text.lower())
                if await self.nouns.german_noun_lookup(check_text) is None:
                    continue

            # handle "Kund(-innen)"
            if text == ")" and "(" in check_text:
                ending_start = check_text.find("(")
                text = check_text[ending_start:]
                start = tokens[token_index - 1].idx + ending_start

            alternatives = rule.alternatives
            explanation = rule.explanation
            url = rule.url
            icon = rule.icon

            if subcategory == "d_and_i":
                if check_case == "gender_denom" and check_text.islower():
                    text_split = text.split(connector_string)
                    if (
                        text_split[0]
                        not in self.static_rules[LangType.DE]["feminine_articles"]
                        or text_split[1]
                        not in self.static_rules[LangType.DE]["masculine_articles"]
                    ):
                        continue

            elif subcategory == "gendered_denominations_ending_advanced":
                if check_text.islower():
                    if (
                        connector_string == "/"
                        and tokens[token_index - 1].text.islower()
                    ):
                        text = tokens[token_index - 1].text + text

                    text_split = text.split(connector_string)
                    if (
                        text_split[0]
                        not in self.static_rules[LangType.DE]["feminine_articles"]
                        or text_split[1]
                        not in self.static_rules[LangType.DE]["masculine_articles"]
                    ):
                        continue

                    alternatives = [
                        Alternative(
                            text.replace(
                                connector_string, config.german_gender_ending[0]
                            )
                        )
                    ]
                # Kundinnen -> Kund*innen
                elif text.lower().endswith("innen") or text.lower().endswith("innen)"):
                    alternatives = [Alternative(alternatives[0].lemma + "nen")]
            elif subcategory.startswith("gender_specific_abbreviation"):
                has_advanced = is_sub_category_enabled(
                    config.disabled_categories, "gender_specific_abbreviation_advanced"
                )

                parenthesis = (
                    token_index > 0
                    and tokens[token_index - 1].text == "("
                    and len(tokens) > token_index + len(text)
                    and tokens[token_index + len(text)].text == ")"
                )

                letters = text
                if parenthesis:
                    letters = letters[1:-1]

                letters = text.split("/")

                letters = list(map(lambda x: x.upper(), letters))
                is_lower = text[0].islower()

                all_letters = deepcopy(letters)

                veteran_letter = "V"
                diverse_letter = "D"
                if diverse_letter not in letters and "*" not in letters:
                    letters.append(diverse_letter)
                elif not has_advanced:
                    continue

                x_letter = "X"
                without_x = True
                if "X" in letters:
                    letters.remove("X")
                    without_x = False

                without_v = True
                if "V" in letters:
                    letters.remove("V")
                    without_v = False

                if "W" in letters:
                    for letter_index in range(len(letters)):
                        if letters[letter_index] == "W":
                            letters[letter_index] = "F"
                            break

                if has_advanced:
                    letters = sorted(letters)

                alternative = "/".join(letters)
                if is_lower:
                    alternative = alternative.lower()
                    diverse_letter = diverse_letter.lower()
                    veteran_letter = veteran_letter.lower()
                    x_letter = x_letter.lower()

                if parenthesis:
                    start -= 1
                    text = f"({text})"
                    alternative = f"({alternative})"

                context_v = "include veterans"
                context_d = language.translate("GENDERABBREVIATIONCONTEXT")
                context_remove = language.translate("GENDERABBREVIATIONCONTEXTREMOVE")
                explanation = language.translate("GENDERABBREVIATIONEXPLANATION")

                if language.lang == LangType.DE:
                    alternative = alternative.replace("f", "w")

                alternative_3 = None
                alternative = Alternative(alternative)
                if "*" in alternative.lemma:
                    alternative_2 = alternative.lemma.replace("*", diverse_letter)
                    alternative_v = alternative_2
                    alternative_2 = Alternative(alternative_2)
                    alternative_2.label = context_d
                    if not without_x:
                        alternative_3 = alternative.lemma.replace("*", x_letter)
                        alternative_3 = Alternative(alternative_3)
                else:
                    alternative_2 = alternative.lemma.replace(diverse_letter, "*")
                    alternative_2 = Alternative(alternative_2)
                    alternative_v = alternative.lemma
                    if not without_x:
                        alternative_3 = alternative.lemma.replace(
                            diverse_letter, x_letter
                        )
                        alternative_3 = Alternative(alternative_3)

                    alternative.label = context_d

                if language.lang == LangType.EN:
                    alternative_v = alternative_v.replace(
                        diverse_letter, diverse_letter + "/" + veteran_letter
                    )
                    alternative_v = Alternative(alternative_v)

                    if without_v is False:
                        alternative_v.label = context_d
                        alternative = alternative_v
                    else:
                        alternative_v.label = context_v

                remove_alternative = Alternative("-")
                remove_alternative.is_remove = True
                remove_alternative.label = context_remove
                alternatives = [
                    remove_alternative,
                    Alternative(language.translate("ALLGENDER")),
                ]

                # case "d/f/m/v" => do not suggest "d/v/f/m"
                if (
                    len(all_letters) < len(alternative.lemma.split("/"))
                    or (all_letters[0] != "d" and all_letters[0] != "*")
                    or all_letters[-1] != "m"
                ):
                    alternatives.append(alternative)

                if not has_advanced:
                    alternative_sorted = Alternative("/".join(sorted(letters)))
                    alternative_sorted.label = context_d

                    if parenthesis:
                        alternative_sorted.lemma = f"({alternative_sorted.lemma})"

                    if is_lower:
                        alternative_sorted.lemma = alternative_sorted.lemma.lower()

                    alternatives.append(alternative_sorted)

                if language.lang == LangType.EN and without_v:
                    alternatives.append(alternative_v)

                if language.lang == LangType.DE or "*" in alternative.lemma:
                    alternatives.append(alternative_2)

                if alternative_3 is not None:
                    alternatives.append(alternative_3)

            skip_token = start_token + 1

            list_full.append(
                ResultOut.factory(
                    config,
                    client,
                    language,
                    text,
                    rule.text_id,
                    full_text,
                    offsets,
                    subcategory,
                    start,
                    None,
                    alternatives,
                    None,
                    explanation,
                    url,
                    icon,
                )
            )

            return skip_token

        return token_index
