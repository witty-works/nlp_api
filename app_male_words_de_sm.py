import os
os.environ['KMP_DUPLICATE_LIB_OK']='True'
import pandas as pd
import spacy
import re
from fastapi import FastAPI

# load German spacy pre-built model
model = spacy.load('de_core_news_sm')

# load MaleCodedTerms_de
df_male_ct = pd.read_csv("df_male_ct_new_de.csv")

app = FastAPI()

@app.get('/')
def get_root():
    return {'message': 'This is the MaleCodedTerms analysis app'}


@app.get('/pos-en/')
async def query_pos_analysis(text: str):
    return analyze_male(text)


def analyze_male(text):
    """Get and process result"""
    #apply SpaCy German pre/built model
    doc = model(text)
    #check if the user request contains the Male Coded terms from the csv file. Keep the punctuation. Compare the lemma of the token (canonical form) in the user query is the words from csv table
    for token in doc:
    	for index, row in df_male_ct.iterrows():
    		if token.lemma_ == row["MaleCodedWords"]:
    			# Format and return results
    			return {"word": row["MaleCodedWords"], "category": "Male Coded Terms", "start": token.idx, "length": len(token.text), "alternatives": row["Alternatives_split"]}
