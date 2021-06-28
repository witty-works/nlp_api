import os
os.environ['KMP_DUPLICATE_LIB_OK']='True'
import spacy
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List

# load English spacy pre-built model
model = spacy.load("en_core_web_trf")

app = FastAPI()
#format of the input string
class UserRequestIn(BaseModel):
    text: str
#output format
class EntityOut(BaseModel):
    start: int
    end: int
    type: str
    text: str

class EntitiesOut(BaseModel):
    entities: List[EntityOut]

@app.post("/entities", response_model=EntitiesOut)

async def read_entities(user_request_in: UserRequestIn):
    #apply SpaCy English pre-built model
    doc = model(user_request_in.text)
    #extract Named entities, start and end of the word, label and the word itself
    return {
        "entities": [
            {
                "start": ent.start_char,
                "end": ent.end_char,
                "type": ent.label_,
                "text": ent.text,
            } for ent in doc.ents
        ]
    }