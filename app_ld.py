
from fastapi import FastAPI
#libraries to format the input&output
from pydantic import BaseModel
from typing import List
#libraries for language Detect
from langdetect import detect
from langdetect import DetectorFactory
#For the reproducible results
DetectorFactory.seed = 0

app = FastAPI()

class UserRequestIn(BaseModel):
    text: str


@app.post("/language_detect", response_model=str())
async def read_text(user_request_in: UserRequestIn):
    lang = detect(user_request_in.text)
    return {"language":lang}