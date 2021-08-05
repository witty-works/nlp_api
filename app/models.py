from pydantic import BaseModel
from typing import List
from typing import Optional

class UserRequestIn(BaseModel):
    text: str
    lang: Optional[str] = "auto"
    fallback_lang: Optional[str]

class EntityOut(BaseModel):
    start: int
    end: int
    type: str
    text: str

class EntitiesOut(BaseModel):
    entities: List[EntityOut]
    language: str
