import fasttext
import os


class LangDetection:
    def __init__(self):
        pretrained_lang_model = os.getcwd() + "/training_data/lid.176.bin"
        self.model = fasttext.load_model(pretrained_lang_model)

    def predict_lang(self, text, langs_max_match_count=5, threshold=0.2):
        langs, predictions = self.model.predict(
            text.replace("\n", " "), k=langs_max_match_count, threshold=threshold
        )

        result = []
        i = 0
        for lang in langs:
            result.append(lang[-2:])
            i += 1

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
            if lang != None:
                return lang

        return None

    def get_locale(self, text, lang, language_preferences, variant_preferences):
        if lang == "auto":
            langs = self.predict_lang(text)

            locale = self.get_locale_by_variant(langs, variant_preferences)
            if locale != None:
                return locale

            return self.get_locale_by_lang(langs, language_preferences)

        if lang in self.supported_langs:
            if lang in self.supported_locales:
                return lang

            return self.get_default_locale(lang)

        return None
