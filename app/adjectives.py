from spacy.tokens import Token, Doc
from inflex import Adjective

from app.settings import Settings
from app.models import LangType, WordType
from app.logger import Logger
from app.helper import check_word_case, get_target_declension_form, find_matching_form
from app.db import Db

class Adjectives:
    settings: Settings
    logger: Logger
    db: Db

    def __init__(
        self,
        settings: Settings,
        logger: Logger,
        db: Db,
    ):
        self.settings = settings
        self.logger = logger
        self.db = db

    def align_form_adjective_english(
        self,
        target_form: str | None,
        source_text: str,
        source_lemma: str,
        target_token: Token,
        target_result: dict | None,
    ) -> str:
        # use a_token.text to handle "consulting"
        source_text_lower = source_text.lower()

        if target_form is None:
            # Fallback code
            a_adjective_lemma = Adjective(source_lemma)
            if a_adjective_lemma.is_singular() == source_text_lower:
                target_form = "singular"
            elif a_adjective_lemma.comparative() == source_text_lower:
                target_form = "comparative"
            elif a_adjective_lemma.superlative() == source_text_lower:
                target_form = "superlative"
            else:
                target_form = None

        if target_form is None:
            if self.settings.log_missing_declension and len(source_text) > 2:
                self.logger.error(
                    f"English adjective target form could not be determined for '{source_text}' (lemma: '{source_lemma}')."
                )

            return target_token.text

        if target_result is None:
            b_adjective = Adjective(target_token.lemma_)

            if target_form == "singular":
                text = b_adjective.singular()
            elif target_form == "comparative":
                text = b_adjective.comparative()
            elif target_form == "superlative":
                text = b_adjective.superlative()
            else:
                text = target_token.text

            if self.settings.log_missing_declension and check_word_case(
                target_token.text, False
            ):
                self.logger.error(
                    f"English adjective data missing for '{target_token.text}' (lemma: '{target_token.lemma_}'), generated '{text}' for target form '{str(target_form)}'."
                )

            return text

        text = get_target_declension_form(target_result, target_form)
        if text is None:
            if self.settings.log_missing_declension and len(target_token.text) > 2:
                self.logger.error(
                    f"English adjective target form '{str(target_form)}' for '{target_token.text}' (lemma: '{target_token.lemma_}') missing: {json.dumps(target_result)}"
                )

            return target_token.text

        return text

    def align_form_adjective_german(
        self,
        target_form: str,
        target_token: Token,
        target_result: dict,
    ) -> str:
        text = target_token.text
        if target_result is not None and text != target_result["base_form"]:
            return text

        if target_form is None:
            ending = ""
        elif target_form in [
            "base_form",
            "comparative",
            "superlative",
        ]:
            text_aligned = get_target_declension_form(target_result, target_form)
            if text_aligned is not None:
                return text_aligned

            ending = ""
        else:
            ending = target_form

        if target_result is not None:
            if ending != "ste":
                if target_result["is_absolute"] == True:
                    return text
            elif target_result is not None:
                text = target_result["superlative"].removesuffix("sten")

        if len(ending) and ending[0] != "e":
            if not ending.startswith("ste"):
                ending = ""
            elif text.endswith("t") or text.endswith("s"):
                ending = "e" + ending
        elif text[-1] == "e":
            ending = ending[1:]

        return text + ending

    def align_form_adjective_french(
        self,
        target_form: str,
        target_token: Token,
    ) -> str:
        text = target_token.text

        if target_form == "performantes":
            if text.endswith("l") or text.endswith("é"):
                text += "e"

            text += "s"
        elif target_form == "ambitieuse":
            if text.endswith("é"):
                text += "e"

        return text

    async def align_form_adjective(
        self,
        lang: LangType,
        target_form: str,
        source_text: str,
        source_lemma: str,
        target_token: Token,
    ) -> str:
        if target_form == "no_change" or target_form is None:
            return target_token.text

        if lang == LangType.FR:
            return self.align_form_adjective_french(target_form, target_token)

        target_result = await self.db.fetch_declensions(
            lang, WordType.ADJECTIVE, target_token.text, target_token
        )

        if lang == LangType.DE:
            return self.align_form_adjective_german(
                target_form, target_token, target_result
            )

        return self.align_form_adjective_english(
            target_form, source_text, source_lemma, target_token, target_result
        )

    async def find_form_adjective_german(self, token_index: int, tokens: Doc):
        token = tokens[token_index]
        forms = await self.db.fetch_declensions(
            LangType.DE, WordType.ADJECTIVE, token.text, token
        )

        if forms is not None and forms["is_absolute"] == False:
            target_form = find_matching_form(forms, token.text)

            if target_form is not None:
                return target_form

        if len(token.text) < 2:
            ending = ""
        elif token.text.endswith("sten"):
            ending = "sten"
        elif token.text.endswith("ste"):
            ending = "ste"
        else:
            ending = token.text[-2:]
            if ending[0] != "e":
                ending = ending[1:]

        return ending

    async def find_form_adjective_english(self, token_index: int, tokens: Doc):
        token = tokens[token_index]
        forms = await self.db.fetch_declensions(
            LangType.EN, WordType.ADJECTIVE, token.text, token
        )

        if forms is not None:
            if forms["is_absolute"]:
                return "no_change"

            target_form = find_matching_form(forms, token.text)
            if target_form is not None:
                return target_form

        # Fallback code
        text_lower = token.text.lower()
        if text_lower == token.lemma_:
            target_form = "no_change"
        else:
            adjective = Adjective(token.lemma_.lower())

            if adjective.is_singular() == text_lower:
                target_form = "singular"
            elif adjective.comparative() == text_lower:
                target_form = "comparative"
            elif adjective.superlative() == text_lower:
                target_form = "superlative"
            else:
                target_form = None

        if (
            target_form is None
            and self.settings.log_missing_declension
            and len(token.text) > 2
            and check_word_case(token.text, False)
        ):
            self.logger.error(
                f"English adjective target form could not be determined for '{token.text}' (lemma: '{token.lemma_}', idx: '{token.idx}')."
            )

        return target_form
