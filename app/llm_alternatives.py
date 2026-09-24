from app.settings import Settings
from app.models import (
    RephraseRequestIn,
    LangType,
    Config,
)
from app.alternatives import Alternatives
from app.prompt import Prompt
import json
import logging


lang_map = {
    LangType.EN: "English",
    LangType.DE: "German",
    LangType.FR: "French",
}


class LlmAlternatives:
    settings: Settings
    alternatives: Alternatives
    prompt: Prompt

    def __init__(self, settings: Settings, alternatives: Alternatives, prompt: Prompt):
        self.settings = settings
        self.alternatives = alternatives
        self.prompt = prompt

    async def handle(
        self,
        rephrase_request_in: RephraseRequestIn,
    ):
        sentence = rephrase_request_in.sentence
        alternatives = []
        collective_nouns = []
        genderstar = {}
        for alternative_index in range(len(rephrase_request_in.alternatives)):
            alternative = rephrase_request_in.alternatives[alternative_index]
            if (
                alternative.gender_role is None
                or rephrase_request_in.lang == LangType.EN
            ):
                alternatives.append(alternative.text)
                if alternative.collective_noun == True:
                    collective_nouns.append(alternative.text)
            else:
                genderstar[alternative_index] = alternative.gender_role
                alternatives.append(alternative.male_form)
                alternatives.append(alternative.female_form)

        alternatives = list(set(alternatives))

        text = rephrase_request_in.text
        start = rephrase_request_in.start
        lang = lang_map[rephrase_request_in.lang]

        end = start + len(text)

        # The code puts each alternative in place of `text`; the model only
        # makes it fit. Asking the model to do the replacement itself, as this
        # used to, left more agreement errors with every model tried, and let
        # it restyle the rest of the sentence.
        # The swapped-in words are marked, so the model knows which words to
        # adapt and which occurrence was replaced.
        drafts = {
            alternative: sentence[:start] + f"⟦{alternative}⟧" + sentence[end:]
            for alternative in alternatives
        }

        system_prompt = f"""
        You fix {lang} grammar after a word swap.
        In each sentence of "sentences", the words in ⟦ ⟧ replaced the words
        "{text}" of "original". They may be a base form: an infinitive, a
        singular, a masculine or feminine form.
        Rewrite each sentence so they fit, and remove the ⟦ ⟧:
        - Give the words in ⟦ ⟧ the grammatical form "{text}" had in
          "original": the same tense, person, number and case. If "{text}" is
          past tense, they become past tense too.
        - Make the words that depend on them agree with them: articles,
          adjectives, pronouns referring to them, the verb.
        - Change nothing else. Every other word stays exactly as it is, even
          where it repeats "{text}" elsewhere in the sentence, and so do
          spelling mistakes, gender-inclusive forms such as Kund*innen or
          expert·es, and double parentheses.
        An expression listed in "collective_nouns" names a group: keep it, and
        make the words that depend on it agree with it.
        Answer with a JSON object mapping each key of "sentences" to its
        rewritten sentence, and nothing else.
        """

        input_data = {
            "original": sentence,
            "sentences": drafts,
            "collective_nouns": collective_nouns,
        }

        user_prompt = json.dumps(input_data, ensure_ascii=False)

        # `model` is a debug-only override; it is None for every other caller,
        # and Prompt falls back to the configured one.
        answer = await self.prompt.handle(
            user_prompt, system_prompt, rephrase_request_in.model
        )
        parsed = self.prompt.parse_json(answer)
        # Anything but an object of sentences is no rephrasing: prose, a
        # reasoning model cut off mid-thought, a list. Keep only the strings.
        if not isinstance(parsed, dict):
            logging.getLogger("nlp_api").warning(
                "LLM rephrasing was not a JSON object: %r", str(answer)[:200]
            )
            parsed = {}
        # A mark the model left in is not part of the sentence.
        result = {
            key: value.replace("⟦", "").replace("⟧", "")
            for key, value in parsed.items()
            if isinstance(value, str)
        }

        separator, noun_separator, separate_gender_plural = (
            Config.get_gender_separators(rephrase_request_in.gender_separator)
        )

        results = {}
        for alternative_index in range(len(rephrase_request_in.alternatives)):
            alternative = rephrase_request_in.alternatives[alternative_index]
            if alternative_index in genderstar:
                if (
                    alternative.male_form in result
                    and alternative.female_form in result
                ):
                    alternative.male_form, alternative.female_form, rephrasings = (
                        await self.alternatives.noun_alternatives(
                            rephrase_request_in.lang,
                            separator,
                            noun_separator,
                            separate_gender_plural,
                            result[alternative.male_form],
                            result[alternative.female_form],
                        )
                    )

                    gendered_role_format = genderstar[alternative_index]
                    if genderstar[alternative_index] in rephrasings:
                        results[alternative.text] = rephrasings[gendered_role_format]
            elif alternative.text in result:
                results[alternative.text] = result[alternative.text]

        return results
