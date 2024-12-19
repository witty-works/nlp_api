from inflex import Noun
from app.models import (
    LangType,
    WordType,
    Alternative,
)
from app.model import Model
from app.helper import (
    upperfirst,
    check_word_case,
    get_target_declension_form,
    find_matching_form,
    remove_gender_ending,
)
from app.db import Db
from app.settings import Settings
from app.categories import is_sub_category_enabled, make_category_advanced

import json
from spacy.tokens import Token, Doc
from logging import Logger
from german_nouns.lookup import Nouns as GermanNouns


class Nouns:
    settings: Settings
    logger: Logger
    static_rules: dict
    model: Model
    db: Db

    def __init__(
        self,
        settings: Settings,
        logger: Logger,
        static_rules: dict,
        model: Model,
        db: Db,
    ):
        self.settings = settings
        self.logger = logger
        self.static_rules = static_rules
        self.model = model
        self.db = db
        self.nouns = GermanNouns()

        self.noun_form_map = {
            "nominativ singular": "sg_nom",
            "dativ singular": "sg_dat",
            "akkusativ singular": "sg_acc",
            "genitiv singular": "sg_gen",
            "nominativ plural": "pl_nom",
            "dativ plural": "pl_dat",
            "akkusativ plural": "pl_acc",
            "genitiv plural": "pl_gen",
        }

    async def german_noun_lookup(
        self, text: str, token: Token | None = None, prefix: str | None = None
    ) -> dict:
        word = text
        forms = await self.db.fetch_declensions(LangType.DE, WordType.NOUN, word, token)
        if forms is not None:
            return forms

        if word.endswith("-"):
            if word.endswith("s-"):
                postfix = "s-"
            else:
                # Handle cases like: Kunde---
                postfix = "-" * (len(word) - len(word.rstrip("-")))

            word = word[0 : -1 * len(postfix)]
            forms = await self.db.fetch_declensions(
                LangType.DE, WordType.NOUN, word, token
            )
        else:
            postfix = ""

        lower = False
        if prefix is None:
            prefix = ""

        if forms is None:
            if prefix != "":
                word = upperfirst(word.removeprefix(prefix))
                lower = not prefix.endswith("-")
                forms = await self.db.fetch_declensions(
                    LangType.DE, WordType.NOUN, word, token
                )

            if forms is None:
                if "-" in word:
                    words = word.rstrip("-").split("-")
                    word = words[-1]
                    forms = await self.db.fetch_declensions(
                        LangType.DE, WordType.NOUN, word, token
                    )
                    if len(words) > 1:
                        prefix = "-".join(words[0:-1]) + "-"
                else:
                    lower = True
                    prefix = ""

                while len(word) > 3 and forms is None:
                    words = self.nouns.parse_compound(word)
                    if len(words) == 0:
                        for substring in self.static_rules[LangType.DE][
                            "german_nouns_postfix"
                        ]:
                            position = text.find(substring)
                            if position >= 0:
                                words = [text[0:position], upperfirst(text[position:])]
                                break

                        if len(words) == 0:
                            break

                    # Konzernverantwortlicher gets split into 'Konzern' + 'Verantwortliche'
                    if len(words[-1]) > 3 and word[-1] != words[-1][-1]:
                        forms = await self.db.fetch_declensions(
                            LangType.DE, WordType.NOUN, words[-1] + word[-1], token
                        )

                    if forms is None:
                        word = words[-1]
                        forms = await self.db.fetch_declensions(
                            LangType.DE, WordType.NOUN, word, token
                        )
                        if forms is None and len(words) > 2:
                            word = words[-2] + words[-1].lower()
                            forms = await self.db.fetch_declensions(
                                LangType.DE, WordType.NOUN, word, token
                            )

                    if forms is not None:
                        for form in forms:
                            if forms[form] is None:
                                continue

                            ending_lower = forms[form].lower()
                            if text.endswith(ending_lower + postfix):
                                lower = True
                                prefix += text.removesuffix(ending_lower + postfix)
                                break

        if forms is not None and (prefix != "" or postfix != ""):
            for form in forms:
                if not form.startswith("gender") and forms[form] is not None:
                    forms[form] = (
                        prefix
                        + (forms[form].lower() if lower else forms[form])
                        + postfix
                    )

        return forms

    async def german_noun_gender_lookup(self, word: str) -> str:
        if word.endswith("leute") or word.endswith("kraft") or word.endswith("person"):
            return "feminine"

        result = await self.german_noun_lookup(word)
        if result is None:
            gender = self.determine_gender_from_ending(
                word, self.static_rules[LangType.DE]["primary_german_gender_endings"]
            )

            if gender is None:
                gender = self.determine_gender_from_ending(
                    word,
                    self.static_rules[LangType.DE]["secondary_german_gender_endings"],
                )

            return gender

        return result["gender_1"]

    def determine_gender_from_ending(
        self, word: str, german_gender_endings: list
    ) -> str | None:
        for gender in german_gender_endings:
            for ending in german_gender_endings[gender]:
                if word.endswith(ending):
                    return gender

        return None

    async def find_form_noun_german(
        self, token_index: int, tokens: Doc, is_singular: bool | None = None
    ):
        token = tokens[token_index]

        if await self.model.check_word_type(
            LangType.DE, token, WordType.PRONOUN, True, True
        ):
            return "no_change"

        return await self.find_form_noun_german_text(token.text, token, is_singular)

    def fetch_flexion(self, token: Token) -> str | None:
        flexion = self.fetch_case(token)
        if flexion is None:
            return None

        flexion += " singular" if token.morph.get("Number") == ["Sing"] else " plural"

        return flexion

    def fetch_case(self, token: Token) -> str | None:
        match token.morph.get("Case"):
            case ["Dat"]:
                return "dativ"
            case ["Gen"]:
                return "genitiv"
            case ["Nom"]:
                return "nominativ"
            case ["Acc"]:
                return "akkusativ"

        return None

    async def find_form_noun_german_text(
        self, text: str, token: Token, is_singular: bool
    ):
        case = self.fetch_case(token)
        if case:
            flexion = case + " " + ("plural" if is_singular is False else "singular")
            return self.noun_form_map[flexion]

        stripped_text = remove_gender_ending(text)
        forms = await self.german_noun_lookup(stripped_text, token)
        if forms is None:
            if (
                self.settings.log_missing_declension
                and token.ent_type_ == ""
                and len(text) > 2
                and check_word_case(text, True)
                and not await self.model.check_word_type(
                    LangType.DE, token, WordType.PRONOUN, True, True
                )
            ):
                self.logger.error(
                    f"German noun declension not found for '{text}', idx: '{token.idx}'"
                )

            return None

        target_form = find_matching_form(forms, stripped_text, is_singular)
        if (
            target_form is None
            and self.settings.log_missing_declension
            and check_word_case(text, True)
        ):
            self.logger.error(
                f"German noun target form could not be determined for '{text}' (lemma: '{token.lemma_}', idx: '{token.idx}')."
            )

        return target_form

    def is_gender_neutral(self, result: dict | None):
        if result is None:
            return False

        return (
            result["gender_1"] is not None
            and result["gender_2"] is not None
            and result["gender_1"] == "masculine"
            and result["gender_2"] == "feminine"
        )

    async def french_noun_lookup(
        self,
        disabled_categories,
        subcategory: str,
        text: str,
        token: Token,
        alternative: Alternative,
        postfix: list | None = None,
    ) -> dict:
        if text is None:
            return None

        result = await self.db.fetch_declensions(LangType.FR, WordType.NOUN, text)
        if result is None:
            if (
                not text[0].isupper()
                and WordType.NOUN == alternative.get_first_word_type()
            ):
                message = (
                    f"French noun missing for '{text}"
                    + (postfix if postfix else "")
                    + "'"
                    + f" (lemma: '{token.text}', lemma: '{token.lemma_}', idx: '{token.idx}')"
                )

                self.logger.error(message)

            return None

        if (
            result["female_form"]
            and self.is_gender_neutral(result)
            and not is_sub_category_enabled(
                disabled_categories,
                make_category_advanced(subcategory),
            )
        ):
            result["female_form"] = None

        if postfix:
            postfix = " " + (" ".join(postfix))
            for key in ["base_form", "plural", "male_form", "female_form"]:
                if result[key] is None:
                    continue

                result[key] = result[key] + postfix

        return result

    async def find_form_noun_english(self, is_singular: bool):
        if is_singular:
            return "no_change"

        return "plural"

    async def align_form_noun_german(
        self, target_form: str, target_token: Token, prefix: str | None = None
    ) -> str:
        # TODO determine correct form
        if target_token.text.islower() or await self.model.check_word_type(
            LangType.DE, target_token, WordType.PRONOUN, True, True
        ):
            return target_token.text

        target_result = await self.german_noun_lookup(
            target_token.text, target_token, prefix
        )

        text = get_target_declension_form(target_result, target_form)
        if text is None:
            if self.settings.log_missing_declension and check_word_case(
                target_token.text, True
            ):
                self.logger.error(
                    f"German noun target form '{str(target_form)}' for '{target_token.text}' (lemma: '{target_token.lemma_}') missing: '{json.dumps(target_result)}'."
                )

            return target_token.text

        return text

    async def align_form_noun_english(
        self, target_form: str, target_token: Token
    ) -> str:
        if target_token.text == "they":
            return target_token.text

        target_result = await self.db.fetch_declensions(
            LangType.EN, WordType.NOUN, target_token.text, target_token
        )

        text = get_target_declension_form(target_result, target_form)
        if text is None:
            if self.settings.log_missing_declension and check_word_case(
                target_token.text
            ):
                self.logger.error(
                    f"English noun plural for '{target_token.text}' (lemma: '{target_token.lemma_}') missing: '{json.dumps(target_result)}'."
                )

            return Noun(target_token.text).plural()

        return text

    async def align_form_noun(
        self,
        lang: LangType,
        target_form: str,
        target_token: Token,
        prefix: str | None = None,
    ) -> str:
        if target_form == "no_change" or target_form is None or lang == LangType.FR:
            return target_token.text

        if lang == LangType.DE:
            return await self.align_form_noun_german(target_form, target_token, prefix)

        return await self.align_form_noun_english(target_form, target_token)
