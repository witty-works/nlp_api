import gettext

# Libraries for language Detect
from langdetect import detect_langs
from langdetect import DetectorFactory

# For the reproducible results
DetectorFactory.seed = 0

from app.models import UserRequestIn

class Lang(object):
    def __init__(self, user_request_in: UserRequestIn):
        self.locale = self.DetectLanguage(user_request_in)

        langs = {"en": "en_GB", "de": "de_DE"}
        language = gettext.translation("messages", localedir="locales", languages=[langs[self.locale]])
        language.install()
        self._ = language.gettext

    """Detect the language if none is passed explicitly but only return a language if confidence is high enough"""
    def DetectLanguage(self, user_request_in: UserRequestIn):
        allowed_langs = ["en", "de"]

        if user_request_in.lang in allowed_langs:
            return user_request_in.lang

        if user_request_in.lang == None or user_request_in.lang == "auto":
            langs = detect_langs(user_request_in.text)

            for language in langs:
                if language.lang in allowed_langs:
                    return language.lang

            if user_request_in.fallback_lang != None:
                if user_request_in.fallback_lang in allowed_langs:
                    return user_request_in.fallback_lang

                raise Exception("Fallback language not supported: " + user_request_in.fallback_lang)

        raise Exception("Language not supported or could not be determined: " + user_request_in.lang)
