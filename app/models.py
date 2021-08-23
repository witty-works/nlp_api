from pydantic import BaseModel
from typing import List
from typing import Optional

class UserRequestIn(BaseModel):
    text: str
    lang: Optional[str] = "auto"
    fallback_lang: Optional[str] = "de"
    response_lang: Optional[str] = "de_DE"

class EntityOut(BaseModel):
    start: int
    length: int
    category: str
    text: str
    label: str
    reason: str
    solution: str

class EntitiesOut(BaseModel):
    results: List[EntityOut]
    language: str
