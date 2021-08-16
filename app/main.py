import uvicorn

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import os
os.environ['KMP_DUPLICATE_LIB_OK']='True'

# NLP library
import pandas as pd
import spacy
from spacy.matcher import PhraseMatcher
from spacy.matcher import Matcher
#Library for German lemmatization
from HanTa import HanoverTagger as ht
# Regular expression library
import re

# Libraries for language Detect
from langdetect import detect_langs
from langdetect import DetectorFactory

# project models
from app.models import (
    UserRequestIn,
    EntityOut,
    EntitiesOut,
)

# For the reproducible results
DetectorFactory.seed = 0

# Model data
model = {'en': spacy.load("en_core_web_sm"), 'de': spacy.load("de_core_news_sm")}
# load Male coded terms
df_male_ct = pd.read_csv("app/training_data/df_male_ct_new_de.csv")
# load Gender denom_de
df_gender_ct = pd.read_csv("app/training_data/gendered_denom_de.csv")
# load Empty words_de
df_empty_word = pd.read_csv("empty_words_ge.csv")
df_empty_sentences = pd.read_csv("empty_word_sentences_de.csv")

#list of "empty word" sentences
termsEmptyWords = list(df_empty_sentences["EmptyWords-German"])

#Load a Hanover Lab on the TIGER-Corpus trained model.
tagger = ht.HanoverTagger('morphmodel_ger.pgz')

# dictionaries to handle false positives
false_positive = ["selbst", "flexible", "Probleme", "Macht", "unabhängig", "international", "Entwickler"]
exceptions = ["Unternehmen", "Firma", "Gruppe", "Gesellschaft", "Kollektivgesellschaft", "Team", "Organisation"]
terms = ["Kolleginnen und Kollegen", "Kundinnen und Kunden", "Marketing-Team", "Kolleginnen* und Kollegen", "Kundinnen* und Kunden", "Kolleginnen: und Kollegen", "Kundinnen: und Kunden"]

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get('/')
def get_root():
    return {'message': 'Use /docs to get API documentation'}

@app.post("/language_detect", response_model=str())
async def language_detect(user_request_in: UserRequestIn):
    lang = DetectLanguage(user_request_in)

    return {"language":lang}

@app.post("/entities", response_model=EntitiesOut)
async def entities(user_request_in: UserRequestIn):
    lang = DetectLanguage(user_request_in)

    doc = model[lang](user_request_in.text)

    return {
        "entities": [
            {
                "start": ent.start_char,
                "end": ent.end_char,
                "type": ent.label_,
                "text": ent.text,
            } for ent in doc.ents
        ],
        "language": lang
    }

@app.get('/pos-en/')
async def query_pos_analysis(text: str):
    return analyze_query(text)

# Functions
"""Detect the language if none is passed explicitly but only return a language if confidence is high enough"""
def DetectLanguage(user_request_in: UserRequestIn):
    allowed_langs = ['en', 'de']

    if user_request_in.lang in allowed_langs:
        return user_request_in.lang

    if user_request_in.lang == None or user_request_in.lang == "auto":
        langs = detect_langs(user_request_in.text)

        for language in langs:
            if language.lang in allowed_langs:
                return language.lang

    if user_request_in.fallback_lang != None:
        if user_request_in.fallback_lang in allowed_langs:
            return user_request_in.fallback_lang

        raise HTTPException(status_code=400, detail="Fallback language not supported: " + user_request_in.fallback_lang)

    raise HTTPException(status_code=400, detail="Language not supported or could not be determined: " + user_request_in.lang)

"""Function to catch the words related to False Positive in the user query"""
def IsItFalsePositive(word):
    for item in false_positive:
        if word==item:
            return True
    return False

#Phrase matcher part to handle False positives with two words and special simbols
matcher = PhraseMatcher(model["de"].vocab)

# Only run model.make_doc to speed things up
patterns = [model['de'].make_doc(text) for text in terms]
matcher.add("TerminologyList", patterns)

def IfPhraseMatcher(text):
    #doc = model(text)
    matches = matcher(text)
    for match_id, start, end in matches:
        span = text[start:end]
        if span.text in (None, ''):
            return False
        return True

"""Function to handle dependecies of the adjectives."""
def TokenAncestors(token):
    exceptions = ["Unternehmen", "Firma", "Gruppe", "Gesellschaft", "Kollektivgesellschaft", "Team", "Organisation"]
    dic_anc = {}
    if token.pos_ == "ADJ":# or token.tag_== "ADJD":
        dic_anc[tagger.analyze(token.text)[0]] = list(token.ancestors)
        for key in dic_anc.keys():
            if key in false_positive:
                for item in dic_anc[key]:
                    if item.text in exceptions:
                        print({key: "false positive"})

def analyze_male(token):
    """Get and process result"""
    #check if the user request contains the Male Coded terms from the csv file. Keep the punctuation. Compare the lemma of the token (canonical form) in the user query is the words from csv table
    for index, row in df_male_ct.iterrows():
    	if tagger.analyze(token.text)[0] == row["MaleCodedWords"]:
    			# Format and return results
    		return {"word": row["MaleCodedWords"], "category": "Male Coded Terms", "start": token.idx, "length": len(token.text), "alternatives": row["Alternatives_split"]}

# Function to find empty words or sentences
def EmptyWordAnalysis(text):
    tokens = model['de'](text)
    list_tokens = []   
    #Phrase matcher part to handle empty words with two words and special simbols
    matcher = PhraseMatcher(model['de'].vocab)

     # Only run model.make_doc to speed things up
    patterns = [model['de'].make_doc(text) for text in termsEmptyWords]
    matcher.add("TerminologyList", patterns)
    # check if anz empty word in the text
    for token in tokens:
        for index, row in df_empty_word.iterrows():
            if tagger.analyze(token.text)[0] == row["EmptyWords-German"]:
                list_tokens.append('word:')
                list_tokens.append(row["EmptyWords-German"])
                list_tokens.append('start:')
                list_tokens.append(token.idx)
                list_tokens.append('length:')
                list_tokens.append(len(token.text))
                list_tokens.append('category: "Empty words"')

    # found "empty word" sentences
    matches = matcher(tokens)
    for match_id, start, end in matches:
        span = tokens[start:end]      
        list_tokens.append('word:')
        list_tokens.append(span.text)
        list_tokens.append('start:')
        list_tokens.append(span.start_char)
        list_tokens.append('length:')
        list_tokens.append(span.end_char)
        list_tokens.append('category: "Empty words"')
    #return whole list of empty words and sentences
    return list_tokens 

"""Main function to analyse user query. It consists now all functions above"""
def analyze_query(text):
    #apply SpaCy German pre-built model
    tokens = model['de'](text)
    dic_tokens = {}
    dic_anc = {}
    list_tokens = [] 
    for token in tokens:
        #check if the user query have false positives
        if IsItFalsePositive(tagger.analyze(token.text)[0]):
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
                dic_anc[tagger.analyze(token.text)[0]] = list(token.ancestors)
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
                if tagger.analyze(token.text)[0] == row["MaleCodedWords"]:
                    dic_tokens['word'] = row["MaleCodedWords"]
                    dic_tokens["category"] = "Male Coded Terms"
                    dic_tokens['start']= token.idx
                    dic_tokens['length']= len(token.text)
                    dic_tokens["alternatives"] = row["Alternatives_split"]
                # Format and return results
                    return dic_tokens

#check if the user query have "phrase false positives" (two words or more or symbols)
    matches = matcher(tokens)
    for match_id, start, end in matches:
        span = tokens[start:end]
        if len(span.text)==0:
            for token in tokens:
                for index, row in df_gender_ct.iterrows():
                    if tagger.analyze(token.text)[0] == row["Denominations-German"]:
                        dic_tokens['word'] = row["Denominations-German"]
                        dic_tokens["category"] = "Gendered Denom"
                        dic_tokens['start']= token.idx
                        dic_tokens['length']= len(token.text)
                    #dic_tokens["alternatives"] = row["Alternatives_split"]
                # Format and return results

    if IfPhraseMatcher(tokens):
        dic_tokens["False positives"] = span.text
    else:
        for token in tokens:
            for index, row in df_gender_ct.iterrows():
                if tagger.analyze(token.text)[0] == row["Denominations-German"]:
                    dic_tokens['word'] = row["Denominations-German"]
                    dic_tokens["category"] = "Gendered Denom"
                    dic_tokens['start']= token.idx
                    dic_tokens['length']= len(token.text)
                    #dic_tokens["alternatives"] = row["Alternatives_split"]
                # Format and return results
    return dic_tokens

#Phrase matcher part to handle empty words with two words and special simbols
    matcher = PhraseMatcher(model['de'].vocab)

     # Only run model.make_doc to speed things up
    patterns = [model['de'].make_doc(text) for text in termsEmptyWords]
    matcher.add("TerminologyList", patterns)
    # check if anz empty word in the text
    for token in tokens:
        for index, row in df_empty_word.iterrows():
            if tagger.analyze(token.text)[0] == row["EmptyWords-German"]:
                list_tokens.append('word:')
                list_tokens.append(row["EmptyWords-German"])
                list_tokens.append('start:')
                list_tokens.append(token.idx)
                list_tokens.append('length:')
                list_tokens.append(len(token.text))
                list_tokens.append('category: "Empty words"')

    # found "empty word" sentences
    matches = matcher(tokens)
    for match_id, start, end in matches:
        span = tokens[start:end]      
        list_tokens.append('word:')
        list_tokens.append(span.text)
        list_tokens.append('start:')
        list_tokens.append(span.start_char)
        list_tokens.append('length:')
        list_tokens.append(span.end_char)
        list_tokens.append('category: "Empty words"')
    #return whole list of empty words and sentences
    return list_tokens 


# want to server to run app.py in the folder app as main app, port=8000 is defaut port for the fast api
# reload=True is debag mode in Flask is on, to set =False, when deploy the app to the production
# might be added host="0.0.0.0"
if __name__ == '__main__':
    # If this is being ran directly as a script, run an internal uvicorn server
    # to service API requests
    uvicorn.run(app, host='0.0.0.0', port=8000)
