from app.settings import Settings
from app.models import (
    RephraseRequestIn,
    LangType,
    Config,
)
from app.alternatives import Alternatives
from app.prompt import Prompt
import json


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
        aws_model_id = (
            self.settings.aws_model_id
            if rephrase_request_in.model is None
            else rephrase_request_in.model
        )

        placeholder = "|---|"
        sentence = rephrase_request_in.sentence
        alternatives = []
        collective_nouns = []
        genderstar = {}
        for alternative_index in range(len(rephrase_request_in.alternatives)):
            alternative = rephrase_request_in.alternatives[alternative_index]
            if alternative.type is None:
                alternatives.append(alternative.lemma)
                if alternative.collective_noun == True:
                    collective_nouns.append(alternative.lemma)

            else:
                genderstar[alternative_index] = alternative.type
                alternatives.append(alternative.male_form)
                alternatives.append(alternative.female_form)

        alternatives = list(set(alternatives))

        text = rephrase_request_in.text
        start = rephrase_request_in.start
        lang = lang_map[rephrase_request_in.lang]

        end = start + len(text)

        # The updated prompt specifies that the assistant should only replace the word at the specified position
        system_prompt = f"""
        You are an expert in {lang} grammatical correctness.
        Make sure that all grammatical and spelling mistakes present in 'sentence' are still present in each of the 'rephrasing' in the output.
        Replace '{placeholder}' in 'sentence_with_placeholder' with each of the supplied items in 'alternatives'.
        Before making the replacement ensure that the alternative matches the {lang} grammatical case (tense, pluralization etc.) of the supplied 'text' (ie. if 'text' is past tense the 'alternatives' should all also be made past tense).
        Do not make stylistic or other unnecessary changes in the output.
        Change as little as necessary to make the output grammatically correct in {lang} like correcting the gender of the article to match the 'alternative' preceeding '{placeholder}' it.
        For each item in 'alternatives' provide exactly one item ('alternative' + 'rephrasing') in the response with key in the dictionary matching exactly each of the 'alternative' provided.
        Leave double parenthesis unchanged.
        """

        match rephrase_request_in.lang:
            case LangType.DE:
                system_prompt += f"""
                    Make sure to not remove any useage of the Genderstar.
                    To avoid gendered nouns when possible prefer plural over singular.
                    For "alternatives" also listed under "collective_nouns" assume they contain a plural noun.

                    For the following example:  
                    {{
                        "sentence": "Einhaltung von ethischen Prinzipien.",
                        "sentence_with_placeholder": "Einhaltung von ethischen {placeholder}.",
                        "text": "Prinzipien",
                        "alternatives": [
                            "Ethik",
                            "Methode",
                            "Wert",
                            "Richtlinie",
                            "Regel"
                        ]
                    }}

                    Format the output as follows making sure it is valid JSON:
                    {{
                        "Ethik": "Einhaltung von ethischen Ethiken.",
                        "Methode": "Einhaltung von ethischen Methoden.",
                        "Wert": "Einhaltung von ethischen Werte.",
                        "Richtlinie": "Einhaltung von ethischen Richtlinien.",
                        "Regel": "Einhaltung von ethischen Regeln."
                    }}

                    For the following example:
                    {{
                        "sentence": "Wir arbeiten für unsere Kund*innen, für uns ist der Kunde im Zentrum",
                        "sentence_with_placeholder": "Wir arbeiten für unsere Kund*innen, für uns ist der {placeholder} im Zentrum",
                        "text": "Kunden",
                        "alternatives": [
                            "der Kunde",
                            "die Kundin",
                            "die Kundschaft",
                            "die Konsumenten"
                        ],
                        "collective_nouns": [
                            "die Kundschaft",
                            "die Konsumenten"
                        ]
                    }}

                    Format the output as follows making sure it is valid JSON:
                    {{
                        "der Kunde": "Wir arbeiten für unsere Kund*innen, für uns ist der Kunde im Zentrum",
                        "die Kundin": "Wir arbeiten für unsere Kund*innen, für uns ist die Kundin im Zentrum",
                        "die Kundschaft": "Wir arbeiten für unsere Kund*innen, für uns ist die Kundschaft im Zentrum",
                        "die Konsumenten": "Wir arbeiten für unsere Kund*innen, für uns sind die Konsumenten im Zentrum"
                    }}
                    """
            case LangType.FR:
                system_prompt += f"""
                    Make sure to not remove any useage of the point médian.
                    For "alternatives" not listed under "collective_nouns" avoid gendered nouns when possible prefer plural over singular.

                    For the following example:  
                    {{
                        "sentence": "Face à la concurrence, il était handicapé par son jeune âge.",
                        "sentence_with_placeholder": "Face à la concurrence, il {placeholder} par son jeune âge.",
                        "text": "était handicapé",
                        "alternatives": [
                            "être désavantagée",
                            "être désavantagé"
                            "être pénalisée",
                            "être pénalisé"
                        ]
                    }}

                    Format the output as follows making sure it is valid JSON:
                    {{
                        "être désavantagée": "Face à la concurrence, elle était désavantagée par son jeune âge.",
                        "être désavantagé": "Face à la concurrence, il était désavantagé par son jeune âge.",
                        "être pénalisée": "Face à la concurrence, elle était pénalisée par son jeune âge.",
                        "être pénalisé": "Face à la concurrence, il était pénalisé par son jeune âge."
                    }}

                    For the following example:
                    {{
                        "sentence": "Les beaux traducteurs sont compétent.",
                        "sentence_with_placeholder": "Les {placeholder} sont compétent.",
                        "text": "traducteurs",
                        "alternatives": [
                            "traducteur,
                            "traductrice",
                            "traduction"
                        ],
                        "collective_nouns": [
                            "traduction"
                        ]
                    }}

                    Format the output as follows making sure it is valid JSON:
                    {{
                        "traducteur": "Les beaux traducteurs sont compétent.",
                        "traductrice": "Les belles traductrices sont compétentes.",
                        "traduction": "La beau traduction est compétente"
                    }}
                    """
            # case LangType.EN:
            case _:
                system_prompt += f"""
                    For the following example:  
                    {{
                        "sentence": "Wat he had done is amazing as he is the best.",
                        "sentence_with_placeholder": "Wat {placeholder} has done is amazing as he is the best.",
                        "text": "he",
                        "alternatives": [
                            "they",
                            "he or she",
                            "((given name))"
                        ]
                    }}

                    Format the output as follows making sure it is valid JSON:
                    {{
                        "they": "Wat they have done is amazing as he is the best.",
                        "he or she": "Wat he or she have done is amazing as he is the best.",
                        "((given name))": "Wat ((given name)) have done is amazing as he is the best."
                    }}

                    For the following example:
                    {{
                        "sentence": "We analyzed if this works",
                        "sentence_with_placeholder": "We {placeholder} if this works",
                        "text": "analyzed",
                        "alternatives": [
                            "closely examine"
                        ]
                    }}

                    Format the output as follows making sure it is valid JSON:
                    {{
                        "closely examine": "We closely examined if this works"
                    }}
                    """
        new_sentence_start = "" if start == 0 else sentence[0:start]
        new_sentence_end = "" if end >= len(sentence) else sentence[end:]
        sentence_with_placeholder = new_sentence_start + placeholder + new_sentence_end

        input_data = {
            "sentence": sentence,
            "sentence_with_placeholder": sentence_with_placeholder,
            "text": text,
            "alternatives": alternatives,
            "collective_nouns": collective_nouns,
        }

        user_prompt = (
            "Please process the following input into a valid JSON response:\n"
            + json.dumps(input_data)
        )

        result = await self.prompt.handle(user_prompt, system_prompt, aws_model_id)
        result = self.prompt.parseJson(result)

        if rephrase_request_in.gender_separator is None:
            separator = noun_separator = "∙"
        else:
            separator, noun_separator = Config.get_german_noun_separator(
                rephrase_request_in.gender_separator
            )

        results = {}
        for alternative_index in range(len(rephrase_request_in.alternatives)):
            alternative = rephrase_request_in.alternatives[alternative_index]
            if alternative_index in genderstar:
                if (
                    alternative.male_form in result
                    and placeholder not in result[alternative.male_form]
                    and alternative.female_form in result
                    and placeholder not in result[alternative.female_form]
                ):
                    alternative.male_form, alternative.female_form, rephrasings = (
                        await self.alternatives.noun_alternatives(
                            rephrase_request_in.lang,
                            separator,
                            noun_separator,
                            result[alternative.male_form],
                            result[alternative.female_form],
                        )
                    )

                    gendered_role_format = genderstar[alternative_index]
                    if genderstar[alternative_index] in rephrasings:
                        results[alternative.lemma] = rephrasings[gendered_role_format]
            elif (
                alternative.lemma in result
                and placeholder not in result[alternative.lemma]
            ):
                results[alternative.lemma] = result[alternative.lemma]

        return results
