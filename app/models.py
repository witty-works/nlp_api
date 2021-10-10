from pydantic import BaseModel
from typing import List
from typing import Optional
from enum import Enum

class LangType(str, Enum):
    AUTO = "auto"
    EN = "en"
    DE = "de"

class RequestIn(BaseModel):
    text: str
    lang: Optional[LangType] = "auto"
    id: Optional[str] = None

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

    def factory(lang, text, category, start, end = None, alternatives = [], subcategory = None, label = None, reason = None, solution = None):
        if end == None:
            end = start + len(text)

        if subcategory == None:
            subcategory = category
        elif category == "empty_words":
            subcategory = "empty_words"

        label = label if label != None else lang._("rules." + category + "_label")
        reason = reason if reason != None else lang._("rules." + subcategory + "_reason")
        solution = solution if solution != None else lang._("rules." + subcategory + "_solution")

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