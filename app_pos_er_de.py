import os
os.environ['KMP_DUPLICATE_LIB_OK']='True'

from fastapi import FastAPI
import spacy

model = spacy.load('de_dep_news_trf')

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
# extract nouns, adjectives, named entities recognition
    nouns = []
    adjectives = []
    entities = []
    for ent in doc.ents:
        entities.append(ent.text)

    for token in doc:
        if token.pos_ == 'NOUN':
            nouns.append(token.text)
        if token.tag_ == 'ADJD':
            adjectives.append(token.text)
    return nouns, adjectives, entities


    # Format and return results
    return {'nouns': nouns, 'adjectives': adjectives, 'entities': entities}