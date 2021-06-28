import os
os.environ['KMP_DUPLICATE_LIB_OK']='True'
#NLP library
import spacy
#FastAPI
from fastapi import FastAPI
#custom data types to be defined
from pydantic import BaseModel
#Generic version of list. Useful for annotating return types
from typing import List
# load German spacy pre-built model
model = spacy.load("de_dep_news_trf")

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
    #apply SpaCy German pre-built model
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