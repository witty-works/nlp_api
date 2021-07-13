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
    return analyze_query(text)


false_positive = ["selbst", "flexible", "Probleme", "Macht", "unabhängig", "international", "Entwickler"]
exceptions = ["Unternehmen", "Firma", "Gruppe", "Gesellschaft", "Kollektivgesellschaft", "Team"]

"""Function to catch the words related to False Positive in the user query"""
def IsItFalsePositive(word):
    for item in false_positive:
        if word==item:
            return True
    return False

"""Function to handle dependecies of the adjectives."""
def TokenAncestors(token):
    exceptions = ["Unternehmen", "Firma", "Gruppe", "Gesellschaft", "Kollektivgesellschaft", "Team"]
    dic_anc = {}
    if token.pos_ == "ADJ":# or token.tag_== "ADJD":
        dic_anc[token.lemma_] = list(token.ancestors)
        for key in dic_anc.keys():
            if key in false_positive:
                for item in dic_anc[key]:
                    if item.text in exceptions:
                        print({key: "false positive"})
        


def analyze_male(token):
    """Get and process result""" 
    #check if the user request contains the Male Coded terms from the csv file. Keep the punctuation. Compare the lemma of the token (canonical form) in the user query is the words from csv table
    for index, row in df_male_ct.iterrows():
    	if token.lemma_ == row["MaleCodedWords"]:
    			# Format and return results
    		return {"word": row["MaleCodedWords"], "category": "Male Coded Terms", "start": token.idx, "length": len(token.text), "alternatives": row["Alternatives_split"]}

"""Main function to analyse user query. It consists now all functions above"""
def analyze_query(text):
#apply SpaCy German pre-built model
    tokens = model(text)
    dic_tokens = {}
    dic_anc = {}
    for token in tokens:
        #check if the user query have false positives
        if IsItFalsePositive(token.lemma_):
            #recognise if there is Name of organisation or geographical name in the query
            for entity in tokens.ents:
                if entity.label_ == 'ORG' or 'GPE':
                    dic_tokens['organisation'] = entity.text
                    dic_tokens['FalsePositive']= token.text
                    return dic_tokens
            # check if the word is adverb
            if token.pos_ =="ADV":
                dic_tokens['FalsePositive']= token.text
                return dic_tokens
            # check if the word is adjective and find out how it depends on the other words to feel the contex
            elif token.pos_ == "ADJ":# or token.tag_== "ADJD":
                dic_anc[token.lemma_] = list(token.ancestors)
                for key in dic_anc.keys():
                    if key in false_positive:
                        for item in dic_anc[key]:
                            if item.text in exceptions:
                                dic_tokens['FalsePositive']= token.text
                                return dic_tokens
            else:
                dic_tokens['word'] = token.text
                dic_tokens['start']= token.idx
                dic_tokens['length']= len(token.text)
                return dic_tokens
        else:
            for index, row in df_male_ct.iterrows():
                if token.lemma_ == row["MaleCodedWords"]:
                    dic_tokens['word'] = row["MaleCodedWords"]
                    dic_tokens["category"] = "Male Coded Terms"
                    dic_tokens['start']= token.idx
                    dic_tokens['length']= len(token.text)
                    dic_tokens["alternatives"] = row["Alternatives_split"]
                # Format and return results
                    return dic_tokens
                    