from pydantic import BaseModel, validator
from typing import List
from typing import Optional
from enum import Enum
import gettext

class Lang(object):
    def __init__(self, locale):
        self.locale = locale[0:2]

        if self.locale == "en":
            trans_locale = "en_GB"
        else:
            trans_locale = "de_DE"

        language = gettext.translation(
            "messages",
            localedir="locales",
            languages=[trans_locale]
        )

        language.install()

        self.gettext = language.gettext

    def _(self, message: str, placeholders = {}):
        message = self.gettext(message)

        for key in placeholders:
            message = message.replace("%" + key, placeholders[key])

        return message

class LangType(str, Enum):
    AUTO = "auto"
    EN = "en"
    DE = "de"

class Config(BaseModel):
    primary_language: Optional[str] = "de-DE"
    preferred_languages: Optional[str] = "de,en"
    preferred_variants: Optional[str] = "de-DE,en-GB"
    german_gender_ending: Optional[str] = ":in"
    _gendereddenom_ending = {"/in": "/in", "/-in": "/-in", "_in": "_in", "*in": "\*in", ":in": ":in"}
    disabled_categories: Optional[List] = ""

    @validator("german_gender_ending")
    def valid_german_gender_ending(cls, v: str):
        if v not in cls._gendereddenom_ending:
            raise ValueError("Not supported german_gender_ending")
        return v

    @validator("disabled_categories", pre=True)
    def split_string_values(cls, v):
        if isinstance(v, str):
            return v.split(",")
        return v

class RequestIn(BaseModel):
    text: str
    lang: Optional[LangType] = "auto"
    id: Optional[str] = None
    config: Optional[Config] = Config()

class RequestInEvent(RequestIn):
    alternative: str
    start: int
    end: int

class ResultOut(BaseModel):
    start: int
    end: int
    category: str
    text: str
    label: str
    reason: str
    solution: str
    alternatives: List[str]

    def factory(config: Config, lang: Lang, text, category, start, end = None, alternatives = [], subcategory = None, label = None, reason = None, solution = None):
        if end == None:
            end = start + len(text)

        if subcategory == None:
            subcategory = category
        elif category == "empty_words":
            subcategory = "empty_words"

        params = {}
        if subcategory == "gendered_denominations_ending":
            params["gendered_denominations_ending"] = config.german_gender_ending

        label = label if label != None else lang._("rules." + category + "_label", params)
        reason = reason if reason != None else lang._("rules." + subcategory + "_reason", params)
        solution = solution if solution != None else lang._("rules." + subcategory + "_solution", params)

        # TODO remove as soon as the browser extension can handle the "orthography" and "corporate_rules" category
        if category == "orthography" or category == "corporate_rules":
            category = subcategory = "empty_words"

        return ResultOut(text, category, start, end, alternatives, label, reason, solution)

    factory = staticmethod(factory)

    def __init__(self, text, category, start, end, alternatives, label, reason, solution):
        object.__setattr__(self, 'text', text)
        object.__setattr__(self, 'category', category)
        object.__setattr__(self, 'start', start)
        object.__setattr__(self, 'end', end)
        object.__setattr__(self, 'alternatives', alternatives)
        object.__setattr__(self, 'label', label)
        object.__setattr__(self, 'reason', reason)
        object.__setattr__(self, 'solution', solution)

class ResultsOut(BaseModel):
    results: List[ResultOut]
    language: str

    def factory(results, lang):
        return ResultsOut(results, lang.locale)

    factory = staticmethod(factory)

    def __init__(self, results, language):
        object.__setattr__(self, 'results', results)
        object.__setattr__(self, 'language', language)