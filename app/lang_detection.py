from app.models import LangWithAutoType, Config
from functools import lru_cache


class LangDetection:
    def __init__(self, model):
        self.model = model

    def predict_lang(self, text, langs_max_match_count=5, threshold=0.2):
        langs, predictions = self.model.predict(
            text.replace("\n", " "), k=langs_max_match_count, threshold=threshold
        )

        result = []
        for i in range(len(langs)):
            prediction_min = 0.3 if i == 0 else predictions[0] * 0.9
            if predictions[i] < prediction_min:
                continue

            result.append(langs[i][-2:])

        return result

    def get_default_locale(self, lang):
        if lang == "en":
            return "en-US"

        if lang == "de":
            return "de-DE"

        return None

    def get_locale_by_variant(self, langs, variant_preferences):
        if variant_preferences:
            for lang in langs:
                for variant_preference in variant_preferences:
                    if lang == variant_preference[0:2]:
                        return variant_preference

        return None

    def get_locale_by_lang(self, langs, language_preferences):
        if language_preferences:
            for lang in langs:
                if lang in language_preferences:
                    return self.get_default_locale(lang)

        for lang in langs:
            lang = self.get_default_locale(lang)
            if lang is not None:
                return lang

        return None

    def get_locale(self, text, lang, language_preferences=[], variant_preferences=[]):
        if lang == LangWithAutoType.AUTO:
            langs = self.predict_lang(text)

            locale = self.get_locale_by_variant(langs, variant_preferences)
            if locale is not None:
                return locale

            return self.get_locale_by_lang(langs, language_preferences)

        if lang in Config._supported_locales.default:
            return lang

        if lang in Config._supported_langs.default:
            return self.get_default_locale(lang)

        return None


@lru_cache()
def get_lang_detection(model):
    return LangDetection(model)
