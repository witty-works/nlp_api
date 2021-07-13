import os
os.environ['KMP_DUPLICATE_LIB_OK']='True'
from fastapi import FastAPI
import spacy

model = spacy.load('en_core_web_sm')

app = FastAPI()

#nlp = pipeline(task='sentiment-analysis',
#               model='nlptown/bert-base-multilingual-uncased-sentiment')


@app.get('/')
def get_root():
    return {'message': 'This is the part-of-the-speech and named entities analysis app'}


@app.get('/pos-en/')
async def query_pos_analysis(text: str):
    return analyze_pos(text)


def analyze_pos(text):
    """Get and process result"""

    doc = model(text)
# extract nouns, adjectives, named entities, nouns_phrases recognition
    nouns = []
    adjectives = []
    entities = []
    nouns_phrases = []
    for ent in doc.ents:
        entities.append(ent.text)

    for token in doc:
        if token.pos_ == 'NOUN':
            nouns.append(token.text)
        if token.pos_ == 'ADJ':
            adjectives.append(token.text)
    for chunk in doc.noun_chunks:
        nouns_phrases.append(chunk.text)
    # Format and return results
    return {'nouns': nouns, 'adjectives': adjectives, 'entities': entities, 'nouns_phrases': nouns_phrases}