import uvicorn

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "True"

# NLP library
import pandas as pd
import spacy
from spacy.matcher import PhraseMatcher, Matcher
from spacy.tokens import Doc
#Library for German lemmatization
from HanTa import HanoverTagger as ht
# Regular expression library
import re
# convert string of list into list of the strings
import ast
# project models
from app.models import (
    UserRequestIn,
    ResultOut,
    ResultsOut,
)

from app.lang import (
    Lang,
)

# Model data
model = {"en": spacy.load("en_core_web_sm"), "de": spacy.load("de_core_news_sm")}
# load Male coded terms
df_male_ct = pd.read_csv("training_data/MaleCodedTerms_DE.csv")
# load Gender denom_de
df_gender_ct = pd.read_csv("training_data/gendered_denom_de.csv")
# load discriminating words_de
df_discrim_words = pd.read_csv("training_data/DiscriminatingWords_DE.csv")
# load Empty words_de
df_empty_word = pd.read_csv("training_data/empty_words_ge.csv")
df_empty_sentences = pd.read_csv("training_data/empty_word_sentences_de.csv")
#list of "empty word" sentences
terms_empty = list(df_empty_sentences["EmptyWords-German"])

# load Boasting word and sentences de
df_boast_word = pd.read_csv("training_data/BoastingWords_DE.csv")
df_boast_sentences = pd.read_csv("training_data/BoastingSentences_DE.csv")
#list of "boasting word" sentences
terms_boast = list(df_boast_sentences["Boasting-German"])

# load inslusive words
df_inclusive_words = pd.read_csv("training_data/inclusive_words_de.csv")
# load inslusive sentences
df_inclusive_sentences = pd.read_csv("training_data/invlusive_sentences_de.csv")
# list of "inclusive word" sentences
terms_inclusive = list(df_inclusive_sentences["Inclusive-German"])

# load male coded English words
df_male_coded_words_en = pd.read_csv("training_data/MaleCodedTerms_EN.csv")

#Load a Hanover Lab on the TIGER-Corpus trained model.
tagger = ht.HanoverTagger("morphmodel_ger.pgz")

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

@app.get("/")
def get_root():
    return {"message": "Use /docs to get API documentation"}

@app.get("/form", response_class=HTMLResponse)
def form(request: Request):
    return templates.TemplateResponse("form.html", {"request": request})

@app.post("/check", response_model=ResultsOut)
async def check_query(user_request_in: UserRequestIn):
    try:
        lang = Lang(user_request_in)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    #Main function to analyse user query.
    #apply SpaCy pre-built model
    tokens = model[lang.locale](user_request_in.text)

    #Phrase matcher part to handle False positives with two words and special simbols
    matcher = PhraseMatcher(model[lang.locale].vocab)

    # Only run model.make_doc to speed things up
    patterns = [model[lang.locale].make_doc(user_request_in.text) for text in terms_false_positive]
    matcher.add("TerminologyList", patterns)
    
    #functions for German rules& false positives
    if lang.locale == "de":
        #Male coded words and related false positives catch
        list_male_coded= MaleCodedWordAnalysis(lang, tokens)

        # Empty words&sentences catch
        list_empty_words = EmptyWordAnalysis(lang, tokens, terms_empty, df_empty_word, "EmptyWords-German")

        #Gendered denom. words catch 
        list_gender_denom = GenderedDenomAnalysis(lang, tokens)

        # boasting words&sentences catch
        list_boast = RulesBasedWordsPhraseMatcher(lang, tokens, terms_boast, df_boast_word, "Boasting-German", "boasting_words")
    
        #discriminating words catch
        list_discrim = RulesBased(lang, tokens, df_discrim_words, "Jo", "discriminating_words")
        
        #inclusive words
        list_inclusiv = RulesBasedWordsPhraseMatcher(lang, tokens, terms_inclusive, df_inclusive_words, "Inclusive-German", "inclusive_words")
        # full list
        list_full = list_male_coded+list_empty_words+list_gender_denom+list_boast + list_discrim + list_inclusiv

    #function for English rules
    elif lang.locale == "en":
        list_male_coded = RulesBasedEN(lang, tokens, df_male_coded_words_en, "MaleCodedWords-English", "male_coded_terms")
        list_full = list_male_coded

    return {
        "results": list_full,
        "language": lang.locale
    }

# Functions
"""Function to catch the words related to False Positive in the user query"""
def IsItFalsePositive(word, false_positive):
    for item in false_positive:
        if word == item:
            return True

    return False

def IfPhraseMatcher(lang, tokens):
    #Phrase matcher part to handle False positives with two words and special simbols
    matcher = PhraseMatcher(model[lang.locale].vocab)

    # Only run model.make_doc to speed things up
    patterns = [model[lang.locale].make_doc(text) for text in terms_false_positive]
    matcher.add("TerminologyList", patterns)

    matches = matcher(tokens)
    for match_id, start, end in matches:
        span = tokens[start:end]
        if span.text in (None, ""):
            return False
        return True

"""Function to handle dependecies of the adjectives."""
# this function male coded words& related false positives
def MaleCodedWordAnalysis(lang, tokens):
    category = "male_coded_terms"
    list_tokens = []
    dic_anc = {} 
    list_false_positives = []    

    for token in tokens:
        #check if the user query have false positives
        if IsItFalsePositive(tagger.analyze(token.text)[0], false_positive_male):
            #recognise if there is Name of organisation or geographical name in the query
            for entity in tokens.ents:
                if entity.label_ == "ORG":
                    list_false_positives.append({
                        "false positives": token.text,
                        "category": "MaleCodedWords"                    
                    })

            # check if the word is adverb
            if token.pos_ =="ADV":
                list_false_positives.append({
                    "false positives": token.text,
                    "category": "MaleCodedWords"
                })

                
            # check if the word is adjective and find out how it depends on the other words to feel the contex
            elif token.pos_ == "ADJ":# or token.tag_== "ADJD":
                dic_anc[tagger.analyze(token.text)[0]] = list(token.ancestors)
                for key in dic_anc.keys():
                    if key in false_positive_male:
                        for item in dic_anc[key]:
                            if item.text in exceptions:
                                list_false_positives.append({
                                    "false positives": token.text,
                                    "category": "MaleCodedWords"
                                })
        else:
            for index, row in df_male_ct.iterrows():
                if tagger.analyze(token.text)[0] == row["MaleCodedWords-German"]:
                    list_tokens.append(
                        ResultOut.factory(
                            lang,
                            row["MaleCodedWords-German"],
                            category,
                            token.idx,
                            None,
                            ast.literal_eval(row["Alternatives_split_company"]),
                        )
                    )
            
    return list_tokens     
    
def GenderedDenomAnalysis(lang, tokens):
    category = "gendered_denominations"
    list_tokens = []
    list_false_positives = []    
    matcher = PhraseMatcher(model[lang.locale].vocab)

    # Only run model.make_doc to speed things up
    patterns = [model[lang.locale].make_doc(text) for text in terms_false_positive]
    matcher.add("TerminologyList", patterns)
    matches = matcher(tokens)
    
    old_start = 0
    
    rest_text= []
    
    if matches.__len__() != 0:
        for match_id, start, end in matches:
            span = tokens[start:end]
            list_false_positives.append({"False positives": span.text})
            part = tokens[old_start:start]         
            
            rest_text.append(part.text)       
            old_start = end
            
        docs = list(model[lang.locale].pipe(rest_text))
        c_doc = Doc.from_docs(docs)
        
        for token in c_doc:
            for index, row in df_gender_ct.iterrows():
                if tagger.analyze(token.text)[0] == row["Denominations-German"]:
                    list_tokens.append(
                        ResultOut.factory(
                            lang,
                            row["Denominations-German"],
                            category,
                            token.idx
                        )
                    )
    else:
        print(tokens)
        for token in tokens:
            for index, row in df_gender_ct.iterrows():
                if tagger.analyze(token.text)[0] == row["Denominations-German"]:
                    list_tokens.append(
                        ResultOut.factory(
                            lang,
                            row["Denominations-German"],
                            category,
                            token.idx
                        )
                    )
         
    return list_tokens

# Unified function for Emtz words false positives and rules    
def EmptyWordAnalysis(lang, tokens, terms, df, rules_name):
    category = "empty_words"
    
    list_tokens = []
    list_false_positives = []
    #Phrase matcher part to handle False positives with two words and special simbols
    matcher = PhraseMatcher(model[lang.locale].vocab)

     # Only run model.make_doc to speed things up
    patterns = [model[lang.locale].make_doc(text) for text in terms]
    matcher.add("TerminologyList", patterns)

    for token in tokens:
        #check if the user query have false positives
        if IsItFalsePositive(tagger.analyze(token.text)[0], false_positive_empty):
            #recognise if there is Name of organisation or geographical name in the query
            if len(tokens.ents) > 0:
                #this output will be deleted in production
                list_false_positives.append({
                    "false positives": token.text,    
                    "category": "EmptyWord"                  
                })
            else:
                for index, row in df.iterrows():
                    if tagger.analyze(token.text)[0] == row[rules_name]:
                        list_tokens.append(
                            ResultOut.factory(
                                lang,
                                row[rules_name],
                                category,
                                token.idx,
                            )
                        )
                            
        else:
            for index, row in df.iterrows():
                if tagger.analyze(token.text)[0] == row[rules_name]:
                    list_tokens.append(
                        ResultOut.factory(
                            lang,
                            row[rules_name],
                            category,
                            token.idx,
                        )
                    )

 
    matches = matcher(tokens)
    for match_id, start, end in matches:
        span = tokens[start:end]
        list_tokens.append(
            ResultOut.factory(
                lang,
                span.text,
                category,
                span.start_char,
                span.end_char,
            )
        )        

    return list_tokens 

# Unified function for rules and sentence false positives   
def RulesBasedWordsPhraseMatcher(lang, tokens, terms, df, rules_name, category):
    list_tokens = []
    #Phrase matcher part to handle False positives with two words and special simbols
    matcher = PhraseMatcher(model[lang.locale].vocab)

     # Only run model.make_doc to speed things up
    patterns = [model[lang.locale].make_doc(text) for text in terms]
    matcher.add("TerminologyList", patterns)

    for token in tokens:
        for index, row in df.iterrows():
            if token.lemma_ == row[rules_name]:
                list_tokens.append(
                    ResultOut.factory(
                        lang,
                        row[rules_name],
                        category,
                        token.idx
                    )
                )
    
    matches = matcher(tokens)
    for match_id, start, end in matches:
        span = tokens[start:end]
        list_tokens.append(
            ResultOut.factory(
                lang,
                span.text,
                category,
                span.start_char,
                span.end_char,
            )
        )        

    return list_tokens 

#Unified function for rules
def RulesBased(lang, tokens, df, rules_name, category):
    list_tokens = []
    
    for token in tokens:
        for index, row in df.iterrows():
            if tagger.analyze(token.text)[0] == row[rules_name]:
                list_tokens.append(
                    ResultOut.factory(
                        lang,
                        row[rules_name],
                        category,
                        token.idx,
                    )
                )

    return list_tokens 

#Rules based english function
def RulesBasedEN(lang, tokens, df, rules_name, category):
    list_tokens = []
    
    for token in tokens:
        for index, row in df.iterrows():
            if token.lemma_ == row[rules_name]:
                list_tokens.append(
                    ResultOut.factory(
                        lang,
                        row[rules_name],
                        category,
                        token.idx,
                    )
                )
 
    return list_tokens 

# want to server to run app.py in the folder app as main app, port=8000 is defaut port for the fast api
# reload=True is debag mode in Flask is on, to set =False, when deploy the app to the production
# might be added host="0.0.0.0"
if __name__ == "__main__":
    # If this is being ran directly as a script, run an internal uvicorn server
    # to service API requests
    uvicorn.run(app, host="0.0.0.0", port=8000)
