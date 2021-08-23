import uvicorn

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import os
os.environ['KMP_DUPLICATE_LIB_OK'] = 'True'

import gettext

# NLP library
import pandas as pd
import spacy
from spacy.matcher import PhraseMatcher
from spacy.matcher import Matcher
from spacy.tokens import Doc
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
df_empty_word = pd.read_csv("app/training_data/empty_words_ge.csv")
df_empty_sentences = pd.read_csv("app/training_data/empty_word_sentences_de.csv")
#list of "empty word" sentences
terms_empty = list(df_empty_sentences["EmptyWords-German"])

# load Boasting word and sentences de
df_boast_word = pd.read_csv("app/training_data/BoastingWords_DE.csv")
df_boast_sentences = pd.read_csv("app/training_data/BoastingSentences_DE.csv")
#list of "boasting word" sentences
terms_boast = list(df_boast_sentences["Boasting-German"])


#Load a Hanover Lab on the TIGER-Corpus trained model.
tagger = ht.HanoverTagger('morphmodel_ger.pgz')

# dictionaries to handle false positives
false_positive_male = ["selbst", "flexible", "Probleme", "Macht", "unabhängig", "Entwickler"]
false_positive_empty = ["international"]
exceptions = ["Unternehmen", "Firma", "Gruppe", "Gesellschaft", "Kollektivgesellschaft", "Team", "Organization"]
terms_false_positive = ["Kolleginnen und Kollegen", "Kundinnen und Kunden", "Marketing-Team", "Kolleginnen* und Kollegen", "Kundinnen* und Kunden", "Kolleginnen: und Kollegen", "Kundinnen: und Kunden"]

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

@app.get('/')
def get_root():
    return {'message': 'Use /docs to get API documentation'}

@app.get('/form', response_class=HTMLResponse)
def form(request: Request):
    return templates.TemplateResponse("form.html", {"request": request})

@app.post("/language_detect", response_model=str())
async def language_detect(user_request_in: UserRequestIn):
    lang = DetectLanguage(user_request_in)

    return {"language":lang}

@app.post('/check', response_model=EntitiesOut)
async def check_query(user_request_in: UserRequestIn):
    lang = DetectLanguage(user_request_in)

    allowed_langs = ['en_GB', 'de_DE']

    if user_request_in.response_lang not in allowed_langs:
        raise HTTPException(status_code=400, detail="Response language not supported: " + user_request_in.response_lang)

    language = gettext.translation('messages', localedir='locales', languages=[user_request_in.response_lang])
    language.install()
    _ = language.gettext

    #Main function to analyse user query.
    #apply SpaCy pre-built model
    tokens = model[lang](user_request_in.text)

    #Phrase matcher part to handle False positives with two words and special simbols
    matcher = PhraseMatcher(model[lang].vocab)

    # Only run model.make_doc to speed things up
    patterns = [model[lang].make_doc(user_request_in.text) for text in terms_false_positive]
    matcher.add("TerminologyList", patterns)

    #Male coded words and related false positives catch
    list_male_coded= MaleCodedWordAnalysis(_, tokens)

    # Empty words&sentences catch
    list_empty_words = EmptyWordAnalysis(_, lang, tokens, terms_empty, df_empty_word, "EmptyWords-German")

    #Gendered denom. words catch 
    list_gender_denom = GenderedDenomAnalysis(_, lang, tokens)

    # boasting words&sentences catch
    list_boast = RulesBasedWordsPhraseMatcher(_, lang, tokens, terms_boast, df_boast_word, "Boasting-German", "boasting_words")
    
    # full list
    list_full = list_male_coded+list_empty_words+list_gender_denom+list_boast
 
    return {
        "results": list_full,
        "language": lang
    }

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
def IsItFalsePositive(word, false_positive):
    for item in false_positive:
        if word == item:
            return True
    return False

def IfPhraseMatcher(lang, tokens):
    
    #Phrase matcher part to handle False positives with two words and special simbols
    matcher = PhraseMatcher(model[lang].vocab)

    # Only run model.make_doc to speed things up
    patterns = [model[lang].make_doc(text) for text in terms_false_positive]
    matcher.add("TerminologyList", patterns)

    matches = matcher(tokens)
    for match_id, start, end in matches:
        span = tokens[start:end]
        if span.text in (None, ''):
            return False
        return True

"""Function to handle dependecies of the adjectives."""
# this function male coded words& related false positives
def MaleCodedWordAnalysis(_, tokens):
    category = "male_coded_terms"
    list_tokens = []
    dic_anc = {}     
    for token in tokens:
        #check if the user query have false positives
        if IsItFalsePositive(tagger.analyze(token.text)[0], false_positive_male):
            #recognise if there is Name of organisation or geographical name in the query
            for entity in tokens.ents:
                if entity.label_ == 'ORG':
                    list_tokens.append({"text": token.text,
                                    'start': token.idx,
                                    'length': len(token.text),
                                    "category": "False Positive",
                                    "alternatives": [],
                                    "label": _('rules.age_label'),
                                    "reason": _('rules.age_reason'),
                                    "solution": _('rules.age_solution')
                                    })

            # check if the word is adverb
            if token.pos_ =="ADV":
                list_tokens.append({"text": token.text,
                                    'start': token.idx,
                                    'length': len(token.text),
                                    "category": "False Positive",
                                    "alternatives": [],
                                    "label": _('rules.age_label'),
                                    "reason": _('rules.age_reason'),
                                    "solution": _('rules.age_solution')
                                    })

                #return dic_tokens
            # check if the word is adjective and find out how it depends on the other words to feel the contex
            elif token.pos_ == "ADJ":# or token.tag_== "ADJD":
                dic_anc[tagger.analyze(token.text)[0]] = list(token.ancestors)
                for key in dic_anc.keys():
                    if key in false_positive_male:
                        for item in dic_anc[key]:
                            if item.text in exceptions:
                                list_tokens.append({"text": token.text,
                                    'start': token.idx,
                                    'length': len(token.text),
                                    "category": "False Positive",
                                    "alternatives": [],
                                    "label": _('rules.age_label'),
                                    "reason": _('rules.age_reason'),
                                    "solution": _('rules.age_solution')
                                    })
            else:
                list_tokens.append({"text": token.text,
                                    'start': token.idx,
                                    'length': len(token.text),
                                    "category": category,
                                    "alternatives": [],
                                    "label": _('rules.' + category + '_label'),
                                    "reason": _('rules.' + category + '_reason'),
                                    "solution": _('rules.' + category + '_solution')
                                    })
        else:
            for index, row in df_male_ct.iterrows():
                if tagger.analyze(token.text)[0] == row["MaleCodedWords"]:
                    list_tokens.append({
                                    'text': row["MaleCodedWords"],
                                    'start': token.idx,
                                    'length': len(token.text),
                                    "category": category,
                                    "alternatives": row["Alternatives_split"],
                                    "label": _('rules.' + category + '_label'),
                                    "reason": _('rules.' + category + '_reason'),
                                    "solution": _('rules.' + category + '_solution')
                                    })
            
                    #return dic_tokens
    return list_tokens     
    
def GenderedDenomAnalysis(_, lang, tokens):
    category = "gendered_denominations"
    list_tokens = []

    matcher = PhraseMatcher(model[lang].vocab)

    # Only run model.make_doc to speed things up
    patterns = [model[lang].make_doc(text) for text in terms_false_positive]
    matcher.add("TerminologyList", patterns)
    matches = matcher(tokens)
    print(len(matches))
    old_start = 0
    #old_end = 0
    rest_text= []
    
    if matches.__len__() != 0:
        for match_id, start, end in matches:
            span = tokens[start:end]
            list_tokens.append({"False positives": span.text})
            part = tokens[old_start:start]         
            #old_end = end
            rest_text.append(part.text)       
            old_start = end
            #print(tokens[0:start], tokens[end:len(tokens)])
        docs = list(model[lang].pipe(rest_text))
        c_doc = Doc.from_docs(docs)
        #assert [t.text for t in rest_test]
        #last_part = tokens[old_start:len(tokens)]
        
        for token in c_doc:
            for index, row in df_gender_ct.iterrows():
                if tagger.analyze(token.text)[0] == row["Denominations-German"]:
                    list_tokens.append({"text": row["Denominations-German"],
                                            'start': token.idx,
                                            'length': len(token.text),
                                            "category": category,
                                            "label": _('rules.' + category + '_label'),
                                            "reason": _('rules.' + category + '_reason'),
                                            "solution": _('rules.' + category + '_solution')
                                    })
    else:
        print(tokens)
        for token in tokens:
            for index, row in df_gender_ct.iterrows():
                if tagger.analyze(token.text)[0] == row["Denominations-German"]:
                    list_tokens.append({"text": row["Denominations-German"],
                                            'start': token.idx,
                                            'length': len(token.text),
                                            "category": category,
                                            "label": _('rules.' + category + '_label'),
                                            "reason": _('rules.' + category + '_reason'),
                                            "solution": _('rules.' + category + '_solution')
                                        })
         
    return list_tokens

# Unified function for rules    
def EmptyWordAnalysis(_, lang, tokens, terms, df, rules_name):
    category = "empty_words"

    #dic_tokens = {}
    list_tokens = []
    #dic = {}
    #full = []
    #Phrase matcher part to handle False positives with two words and special simbols
    matcher = PhraseMatcher(model[lang].vocab)

     # Only run model.make_doc to speed things up
    patterns = [model[lang].make_doc(text) for text in terms]
    matcher.add("TerminologyList", patterns)

    for token in tokens:
        #check if the user query have false positives
        if IsItFalsePositive(tagger.analyze(token.text)[0], false_positive_empty):
            #recognise if there is Name of organisation or geographical name in the query
            if len(tokens.ents) > 0:
                #this output will be deleted in production
                list_tokens.append({"text": token.text,
                                    'start': token.idx,
                                    'length': len(token.text),
                                    "category": "False Positive",
                                    "alternatives": [],
                                    "label": _('rules.age_label'),
                                    "reason": _('rules.age_reason'),
                                    "solution": _('rules.age_solution')
                                    })
            else:
                
                for index, row in df.iterrows():
                    if tagger.analyze(token.text)[0] == row[rules_name]:
                        list_tokens.append({"text": row[rules_name],
                                            'start': token.idx,
                                            'length': len(token.text),
                                            "category": category,
                                            "label": _('rules.' + category + '_label'),
                                            "reason": _('rules.' + category + '_reason'),
                                            "solution": _('rules.' + category + '_solution')
                                        })
 
    
    matches = matcher(tokens)
    for match_id, start, end in matches:
        span = tokens[start:end]
        list_tokens.append({"text": span.text,
                            'start': span.start_char,
                            'length': (span.end_char - span.start_char),
                            "category": category,
                            "label": _('rules.' + category + '_label'),
                            "reason": _('rules.' + category + '_reason'),
                            "solution": _('rules.' + category + '_solution')
                            })        

    return list_tokens 

# Unified function for rules    
def RulesBasedWordsPhraseMatcher(_, lang, tokens, terms, df, rules_name, category):
    dic_tokens = {}
    list_tokens = []
    dic = {}
    full = []
    #Phrase matcher part to handle False positives with two words and special simbols
    matcher = PhraseMatcher(model[lang].vocab)

     # Only run model.make_doc to speed things up
    patterns = [model[lang].make_doc(text) for text in terms]
    matcher.add("TerminologyList", patterns)

    for token in tokens:
        for index, row in df.iterrows():
            if tagger.analyze(token.text)[0] == row[rules_name]:
                list_tokens.append({'text': row[rules_name],
                                    'start': token.idx,
                                    'length': len(token.text),
                                    "category": category,
                                    "label": _('rules.' + category + '_label'),
                                    "reason": _('rules.' + category + '_reason'),
                                    "solution": _('rules.' + category + '_solution')
                                    })
    
    matches = matcher(tokens)
    for match_id, start, end in matches:
        span = tokens[start:end]
        list_tokens.append({'text': span.text,
                            'start': span.start_char,
                            'length': (span.end_char - span.start_char),
                            "category": category,
                            "label": _('rules.' + category + '_label'),
                            "reason": _('rules.' + category + '_reason'),
                            "solution": _('rules.' + category + '_solution')
                            })        

    return list_tokens 
# want to server to run app.py in the folder app as main app, port=8000 is defaut port for the fast api
# reload=True is debag mode in Flask is on, to set =False, when deploy the app to the production
# might be added host="0.0.0.0"
if __name__ == '__main__':
    # If this is being ran directly as a script, run an internal uvicorn server
    # to service API requests
    uvicorn.run(app, host='0.0.0.0', port=8000)
