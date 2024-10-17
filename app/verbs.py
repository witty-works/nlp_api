from inflex import Verb
from spacy.tokens import Token, Doc

from app.db import Db
from app.models import WordType, LangType
from app.model import Model
from app.helper import (
    check_word_case,
    find_matching_form,
    get_target_declension_form,
    find_common_prefix,
)
from app.settings import Settings
from logging import Logger


class Verbs:
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

    async def german_verb_splittable(self, word: str) -> str | None:  # pragma: no cover
        if self.settings.log_missing_declension and not word.isupper():
            self.logger.error(
                "Guessing how to split: %s",
                word,
            )

        prefixes = (
            "ge",
            "er",
            "be",
            "ent",
            "emp",
            "ver",
            "zer",
            "hinter",
            "miss",
            "ob",
        )

        if word.startswith(prefixes):
            return None

        prefixes = [
            "ab",
            "an",
            "auf",
            "aus",
            "bei",
            "ein",
            "mit",
            "nach",
            "weg",
            "zu",
            "her",
            "nach",
            "überein",
            "umher",
        ]
        for prefix in prefixes:
            if word.startswith(prefix):
                return prefix

        for prefix in static_rules[LangType.DE]["splittable_words"]:
            if word.startswith(prefix):
                if word in static_rules[LangType.DE]["splittable_words"][prefix]:
                    return prefix

                return None

        # detect "adjective + verb" case
        letter_index = 2  # skip the first 2 letters
        while letter_index < len(word) - 2:  # skip the last 2 letters
            prefix = word[0:letter_index]
            partial_word = word[letter_index:]
            partial_word_result = await self.db.fetch_declensions(
                LangType.DE, WordType.VERB, partial_word
            )
            if partial_word_result is not None:
                tokens = self.model.fetch_tokens(
                    LangType.DE, prefix + " " + partial_word
                )
                if WordType.ADJECTIVE == await self.model.fetch_word_type(
                    LangType.DE, tokens[0]
                ) and WordType.VERB == await self.model.fetch_word_type(
                    LangType.DE, tokens[1]
                ):
                    return prefix

            letter_index += 1

        return None

    async def align_form_verb_german(
        self,
        target_form: str,
        source_text: str,
        source_lemma: str,
        target_token: Token,
        target_result: dict,
    ) -> str:
        text = get_target_declension_form(target_result, target_form)
        if text is not None:
            return text

        target_text = target_token.text

        # check if "zu" was stripped from the word in the lemma
        if source_text.count("zu") > source_lemma.count("zu"):
            prefix = await self.german_verb_splittable(target_text)
            if prefix:
                return prefix + "zu" + target_text[len(prefix) :]

            return "zu " + target_text

        # check if "ge" was stripped from the word in the lemma
        if source_text.count("ge") > source_lemma.count("ge"):
            prefix = await self.german_verb_splittable(target_text)
            if prefix:
                return prefix + "ge" + target_text[len(prefix) :]

            injected_string = "ge"
        else:
            injected_string = ""

        prefix = find_common_prefix(
            source_text,
            source_lemma,
        )

        ending = source_text[len(prefix) :]
        if injected_string and ending[0 : len(injected_string)] == injected_string:
            source_text = prefix + source_text[len(prefix) + len(injected_string) :]
            source_text = source_text.strip()
            prefix = find_common_prefix(source_text, source_lemma)
            ending = source_text[len(prefix) :]

        if (
            (source_lemma[-1] == "t" or source_lemma[-1] == "s")
            and len(ending)
            and ending[0] == "e"
        ):
            ending = ending[1:]

        # likely we did not find a useful ending (ie. 'gewinnen' for case 'gewannen' would give use 'annen')
        if len(ending) > 3:
            ending = ""
        else:
            remove = source_lemma[len(prefix) :]
            if remove:
                target_text = target_text[0 : -len(remove)]

            if ending != "" and len(target_text) > 2:
                if target_text.endswith("em"):
                    ending = ""
                else:
                    e_ending_letters = ["t", "n", "c", "v", "r", "h"]
                    e_start_letters = ["t", "s", "n", "r"]
                    if (
                        target_text[-1] in e_ending_letters
                        and ending[0] in e_start_letters
                    ):
                        # einfachsten
                        if (
                            not target_text.endswith("en")
                            and not target_text.endswith("in")
                            and not target_text.endswith("ön")
                            and target_text[-1] != "h"
                            and ending[0:1] != "st"
                        ) or ending[0] == "n":
                            target_text += "e"
                    elif target_text[-1] == "s":
                        target_text += "s"
                    elif target_text[-1] == "e" and ending[0] == "e":
                        target_text = target_text[0:-1]

        if self.settings.log_missing_declension and not source_text.isupper():
            self.logger.error(
                f"German verb declension not found for '{source_text}' (lemma '{source_lemma}'): prefix '{prefix}', ending '{ending}' applies to '{target_token.text}' => {target_text}"
            )

        return target_text + ending

    def align_form_verb_english(
        self,
        target_form: str | None,
        source_text: str,
        target_token: Token,
        target_result: dict | None,
    ) -> str:
        if target_form is None:
            # Fallback code
            a_verb = Verb(source_text)
            if a_verb.is_singular():
                target_form = "third_person_singular"
            elif a_verb.is_past():
                target_form = "past_tense"
            elif a_verb.is_pres_part():
                target_form = "present_participle"
            elif a_verb.is_past_part():
                target_form = "past_participle"
            else:
                target_form = None

            if self.settings.log_missing_declension and not source_text.isupper():
                self.logger.error(
                    f"English verb target form '{str(target_form)}' determined via fallback for '{source_text}'."
                )

        if target_form is None:
            return target_token.lemma_

        if target_result is None:
            b_verb = Verb(target_token.lemma_.lower())

            if target_form == "third_person_singular":
                text = b_verb.singular()
            elif target_form == "past_tense":
                text = b_verb.past()
            elif target_form == "present_participle":
                text = b_verb.pres_part()
            elif target_form == "past_participle":
                text = b_verb.past_part()
            else:
                text = target_token.lemma_

            if self.settings.log_missing_declension and not target_token.text.isupper():
                self.logger.error(
                    f"English verb target form '{str(target_form)}' for '{target_token.text}' (lemma: '{target_token.lemma_}') generated '{text}'."
                )

            return text

        text = get_target_declension_form(target_result, target_form)
        if text is None:
            if self.settings.log_missing_declension and not target_token.text.isupper():
                self.logger.error(
                    f"English verb target form '{str(target_form)}' for '{target_token.text}' (lemma: '{target_token.lemma_}') missing: '{json.dumps(target_result)}'."
                )

            return text

        return text

    async def align_form_verb(
        self,
        lang: LangType,
        target_form: str,
        source_text: str,
        source_lemma: str,
        target_token: Token,
    ) -> str:
        if target_form == "no_change" or target_form is None or lang == LangType.FR:
            return target_token.text

        target_result = await self.db.fetch_declensions(
            lang, WordType.VERB, target_token.text, target_token
        )

        if lang == LangType.DE:
            return await self.align_form_verb_german(
                target_form, source_text, source_lemma, target_token, target_result
            )

        return self.align_form_verb_english(
            target_form, source_text, target_token, target_result
        )

    async def find_form_verb_german(self, token_index: int, tokens: Doc):
        token = tokens[token_index]
        if token._.form is not None:
            return token._.form

        forms = await self.db.fetch_declensions(
            LangType.DE, WordType.VERB, token.text, token
        )
        if forms is None:
            self.logger.error(
                f"German verb form could not be determined for '{token.text}' (lemma: '{token.lemma_}', idx: '{token.idx}')."
            )

            return None

        target_form = find_matching_form(forms, token.text)
        if (
            target_form is None
            and self.settings.log_missing_declension
            and check_word_case(token.text, False)
        ):
            self.logger.error(
                f"German verb target form could not be determined for '{token.text}' (lemma: '{token.lemma_}', idx: '{token.idx}')."
            )

        return target_form

    async def find_form_verb_english(self, token_index: int, tokens: Doc):
        token = tokens[token_index]
        forms = await self.db.fetch_declensions(
            LangType.EN, WordType.VERB, token.text, token
        )

        if forms is not None:
            target_form = find_matching_form(forms, token.text)
            if target_form is not None:
                return target_form

        # Fallback code
        verb = Verb(token.text)
        if verb.is_singular():
            target_form = "third_person_singular"
        elif verb.is_past():
            target_form = "past_tense"
        elif verb.is_pres_part():
            target_form = "present_participle"
        elif verb.is_past_part():
            target_form = "past_participle"
        else:
            target_form = None

        if (
            target_form is None
            and self.settings.log_missing_declension
            and check_word_case(token.text, False)
        ):
            self.logger.error(
                f"English verb target form could not be determined for '{token.text}' (lemma: '{token.lemma_}', idx: '{token.idx}')."
            )

        return target_form
