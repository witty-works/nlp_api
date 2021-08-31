from pydantic import BaseModel
from typing import List
from typing import Optional

class UserRequestIn(BaseModel):
    text: str
    lang: Optional[str] = "auto"
    fallback_lang: Optional[str] = "de"
    response_lang: Optional[str] = "de_DE"

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

class ResultsOut(BaseModel):
    results: List[ResultOut]
    language: str
