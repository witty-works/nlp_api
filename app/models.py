from pydantic import BaseModel
from typing import List
from typing import Optional

class UserRequestIn(BaseModel):
    text: str
    lang: Optional[str] = "auto"
    fallback_lang: Optional[str] = "de"
    response_lang: Optional[str] = "de_DE"
    id: Optional[str] = "anon"

    def toDict(self):
        return {
            "text": self.text,
            "lang": self.lang,
            "fallback_lang": self.fallback_lang,
            "response_lang": self.response_lang,
        }

class UserRequestInEvent(UserRequestIn):
    alternative: str
    start: int
    end: int

    def toDict(self):
        return {
            "text": self.text,
            "lang": self.lang,
            "fallback_lang": self.fallback_lang,
            "response_lang": self.response_lang,
            "alternative": self.alternative,
            "start": self.start,
            "end": self.end,
        }

class ResultOut(BaseModel):
    start: int
    end: int
    category: str
    text: str
    label: str
    reason: str
    solution: str
    alternatives: List[str]

    def factory(lang, text, category, start, end = None, alternatives = []):
        if end == None:
            end = start + len(text)

        label = lang._("rules." + category + "_label")
        reason = lang._("rules." + category + "_reason")
        solution = lang._("rules." + category + "_solution")

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

    def toDict(self):
        return {
            "start": self.start,
            "end": self.end,
            "category": self.category,
            "text": self.text,
            "label": self.label,
            "reason": self.reason,
            "solution": self.solution,
            "alternatives": self.alternatives,
        }

class ResultsOut(BaseModel):
    results: List[ResultOut]
    language: str

    def factory(results, lang):
        return ResultsOut(results, lang.locale)

    factory = staticmethod(factory)

    def __init__(self, results, language):
        object.__setattr__(self, 'results', results)
        object.__setattr__(self, 'language', language)

    def toDict(self):
        return {
            "results": [result.toDict() for result in self.results],
            "language": self.language,
        }