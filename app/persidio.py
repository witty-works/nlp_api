from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
from presidio_analyzer.nlp_engine import SpacyNlpEngine
from presidio_anonymizer import AnonymizerEngine
from app.lang_detection import LangDetection
from app.model import model


class LoadedSpacyNlpEngine(SpacyNlpEngine):
    def __init__(self, loaded_spacy_models):
        self.nlp = loaded_spacy_models


class Persidio:
    def __init__(self):
        self.lang_detection = LangDetection()

        # @TODO limit to just "words" containing only digits
        numbers_pattern = Pattern(name="numbers_pattern", regex="\d+", score=0.5)
        number_recognizer = PatternRecognizer(
            supported_entity="NUMBER", patterns=[numbers_pattern]
        )

        # @TODO limit to just "words" containing only digits and upper case letters
        cryptic_text_pattern = Pattern(
            name="cryptic_text_pattern", regex="A-Z\d+", score=0.5
        )
        cryptic_text_recognizer = PatternRecognizer(
            supported_entity="CRYPTIC_TEXT", patterns=[cryptic_text_pattern]
        )

        self.analyzer = AnalyzerEngine(
            nlp_engine=LoadedSpacyNlpEngine(loaded_spacy_models=model),
            supported_languages=model.keys(),
        )
        self.analyzer.registry.add_recognizer(number_recognizer)
        self.analyzer.registry.add_recognizer(cryptic_text_recognizer)

        self.anonymizer = AnonymizerEngine()

    def clean_str(self, text: str):
        try:
            locale = self.lang_detection.get_locale(text)
            if locale:
                lang = locale[0:2]
            else:
                lang = "en"

            results = self.analyzer.analyze(text=text, language=lang)

            result = self.anonymizer.anonymize(text=text, analyzer_results=results)

            return result.text
        except:
            pass

        return "-- unable to anonymize --"

    def clean_dict(self, dict):
        for dict_key in dict.keys():
            dict[dict_key] = self.clean_var(dict[dict_key])

        return dict

    def clean_var(self, var):
        if isinstance(var, str):
            var = self.clean_str(var)

        if isinstance(var, dict):
            var = self.clean_dict(var)

        if isinstance(var, list):
            for key in range(len(var)):
                var[key] = self.clean_var(var[key])

        return var
