import uvicorn
import os
import json
import base64
import secrets
import aiohttp
import sentry_sdk
import copy

from sentry_sdk.integrations.asgi import SentryAsgiMiddleware
from sentry_sdk.integrations.aiohttp import AioHttpIntegration
from sentry_sdk import configure_scope

from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, Depends, status

from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

from fastapi.security import HTTPBasic, HTTPBasicCredentials

from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import RedirectResponse, PlainTextResponse
from fastapi.exception_handlers import (
    http_exception_handler,
)

from typing import Optional

os.environ["KMP_DUPLICATE_LIB_OK"] = "True"

# Environment variables
logging_enabled = os.environ.get("LOGGING_ENABLED", None)
sentry_dsn = os.environ.get("SENTRY_DSN", "false")
platform_environment = os.environ.get("PLATFORM_ENVIRONMENT", "local")
languagetool_api = os.environ.get("LANGUAGETOOL_API", "false")
platform_relationships = os.environ.get("PLATFORM_RELATIONSHIPS", None)
basic_auth_username = os.environ.get("API_DOCS_USERNAME", None)
basic_auth_password = os.environ.get("API_DOCS_PASSWORD", None)
basic_auth_enabled = os.environ.get("API_DOCS_AUTH_ENABLED", "false")

from datetime import datetime

# NLP library
import pandas as pd
import spacy
from spacy.matcher import PhraseMatcher
from spacy.tokens import Doc

# Regular expression library
import re
# convert string of list into list of the strings
import ast
# project models
from app.models import (
    Config,
    LangType,
    Lang,
    RequestIn,
    RequestInEvent,
    ResultOut,
    ResultsOut,
)

version = "1.2.0"

app = FastAPI(
    title = "Witty NLP API",
    version = version,
    docs_url = None,
    redoc_url = None,
    openapi_url = None,
)

if sentry_dsn != "false":
    sentry_sdk.init(
        dsn = sentry_dsn,
        traces_sample_rate = 0.2,
        integrations = [AioHttpIntegration()],
        release = version,
        environment = platform_environment
    )

# Uncaught exceptions (like `raise Exception`) should propagate correctly
# to Sentry's error handler
# Middleware will also enable Sentry performance monitoring to work as expected
app.add_middleware(SentryAsgiMiddleware)

# To catch raised `HTTPException` exceptions as per:
# https://fastapi.tiangolo.com/tutorial/handling-errors/
# Might have to add something similar for `RequestValidationError`
@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request, e):
    with configure_scope() as scope:
        scope.set_context("request", request)
        scope.transaction = request.scope["path"][1:]

        sentry_sdk.capture_exception(e)
    return await http_exception_handler(request, e)

languagetool_url = "https://lt.api.witty.works/v2"
if languagetool_api != "false":
    languagetool_url = languagetool_api
elif platform_relationships is not None:
    relationships = json.loads(base64.b64decode(platform_relationships))
    languagetool = relationships["languagetool"][0]
    languagetool_url = "%(scheme)s://%(host)s:%(port)d/v2" % languagetool

security = HTTPBasic(auto_error=False)

basic_auth = {
    "username": basic_auth_username,
    "password": basic_auth_password,
    "enabled": basic_auth_enabled,
}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

categories = {
  "gendered_roles": { "color": "#E9DBB2", "inclusive": False },
  # skipping "gendered_roles" subcategories
  #"gendered_roles_hierachy": { "color": "#E9DBB2", "inclusive": False },
  #"gendered_roles_image": { "color": "#E9DBB2", "inclusive": False },
  #"gendered_denominations": { "color": "#E9DBB2", "inclusive": False },
  "gendered_language": { "color": "#E9DBB2", "inclusive": False },
  "agentic_language": { "color": "#F06464", "inclusive": False },
  "communal_language": { "color": "#5ACFB9", "inclusive": True },
  "d_and_i_words": { "color": "#5ACFB9", "inclusive": True },
  "corporate_rules": { "color": "#37D1E5", "inclusive": False },
  "empty_words": { "color": "#37D1E5", "inclusive": False },
  "boasting_words": { "color": "#37D1E5", "inclusive": False },
  "orthography": { "color": "#37D1E5", "inclusive": False },
  "gendered_pronouns": { "color": "#E9DBB2", "inclusive": False },
  "stereotypes": { "color": "#9489DB", "inclusive": False },
  "gendered_stereotypes": { "color": "#E9DBB2", "inclusive": False },
  "biased_language": { "color": "#9489DB", "inclusive": False },
  # skipping "biased_language" subcategories
  #"ability_bias": { "color": "#9489DB", "inclusive": False },
  #"age_bias_old": { "color": "#9489DB", "inclusive": False },
  #"age_bias_young": { "color": "#9489DB", "inclusive": False },
  #"culture_bias": { "color": "#9489DB", "inclusive": False },
  #"migration_background_bias": { "color": "#9489DB", "inclusive": False },
  #"anti_lgtbqiplus_bias": { "color": "#9489DB", "inclusive": False },
  #"classism_bias": { "color": "#9489DB", "inclusive": False },
  # skipping old/new language is it is not yet implemented
  #"old_language": { "color": "#37D1E5", "inclusive": False },
  #"new_language": { "color": "#37D1E5", "inclusive": False },
  # skipping "job_requirements_bias" 
  #"job_requirements_bias": { "color": "#9489DB", "inclusive": False },
  # skipping "job_requirements_bias" subcategories
  #"requirements_overload": { "color": "#9489DB", "inclusive": False },
  #"education_biased_requirements": { "color": "#9489DB", "inclusive": False },
  #"workload_biased_requirements": { "color": "#9489DB", "inclusive": False },
  #"ethnicity_biased_requirements": { "color": "#9489DB", "inclusive": False },
  #"age_biased_requirements": { "color": "#9489DB", "inclusive": False },
}

categories_with_labels = {}
languages = ["en", "de"]
for language in languages:
    lang = Lang(language)
    categories_with_labels[language] = copy.deepcopy(categories)
    for category in categories_with_labels[language]:
        categories_with_labels[language][category]["label"] = lang._("rules." + category + "_label")

# Model data
model = {"en": spacy.load("en_core_web_sm"), "de": spacy.load("de_core_news_sm")}
#custom lematizer to correct the lemmas in spacy library, to add to the curent spacy lematizer
dict_lemma_lookup = {"international": "international", "internationale": "international", "Meister": "Meister", "kämpfend": "kämpfend", "abgebrüht": "abgebrüht", "beherrschend": "beherrschend", "entscheidend": "entscheidend", "entschlossen": "entschlossen", 'angewiesen': 'angewiesen', 'berührt':'berührt', 'besonnen':'besonnen', 'betreut':'betreut', 'bewegt':'bewegt', 'einfühlend':'einfühlend', 'engagiert':'engagiert', 'entgegenkommend':'entgegenkommend', 'ergreifend':'ergreifend', 'fördernd':'fördernd', 'gerührt':'gerührt', 'heiter':'heiter', 'lieb':'lieb', 'mitfühlend':'mitfühlend', 'mitwirkend':'mitwirkend', 'motiviert':'motiviert', 'nährend':'nährend', 'teilnehmend':'teilnehmend', 'unterstützend':'unterstützend', 'verbindend':'verbindend', 'vermittelnd':'vermittelnd', 'vertraut':'vertraut', 'weich':'weich', 'zusammenhängend':'zusammenhängend', 'zusammenwirkend':'zusammenwirkend', 'zustimmend':'zustimmend', 'jünger':'jünger', 'ausgeprägt': 'ausgeprägt', 'ausgezeichnet':'ausgezeichnet', 'äußerst':'äußerst', 'beeindruckend':'beeindruckend', 'beste':'beste', 'bester':'beste', 'besten':'beste', 'bestem':'beste', 'bestes':'beste', 'etabliert':'etabliert', 'führend':'führend', 'fundiert':'fundiert', 'gewandt': 'gewandt', 'Götter': 'Götter', 'hervorragend':'hervorragend', 'überzeugend':'überzeugend', 'zwingend':'zwingend'}

lookup_table = model["de"].get_pipe("lemmatizer").lookups.get_table("lemma_lookup")
for key in dict_lemma_lookup:
    lookup_table.set(key, dict_lemma_lookup[key])

# load agentic language
df_agentic_ct = pd.read_csv("training_data/agentic_language_DE.csv")
#list_agentic = list(df_agentic_ct["Lemma"])

# load Gender denom_de
df_gender_ct = pd.read_csv("training_data/gendered_denominations_DE.csv")
#load Gender denom_de false_positives
genderdenom_false_positives = pd.read_csv("training_data/genderdenom_false_positives_new.csv")

# load discriminating words_de
df_discrim_words = pd.read_csv("training_data/biased_language_DE.csv")

# load Empty words_de
df_empty_word = pd.read_csv("training_data/empty_words_de.csv")
df_empty_sentences = pd.read_csv("training_data/empty_words_sentences_de.csv")
#list of "empty word" sentences
terms_empty = list(df_empty_sentences["Lemma"])

# load Boasting word and sentences de
df_boast_word = pd.read_csv("training_data/boasting_words_DE.csv")
df_boast_sentences = pd.read_csv("training_data/boasting_words_sentences_DE.csv")
#list of "boasting word" sentences
terms_boast = list(df_boast_sentences["Lemma"])

# load inslusive words
df_d_and_i_words = pd.read_csv("training_data/d_and_i_words_de.csv")
# load inslusive sentences
df_d_and_i_words_sentences = pd.read_csv("training_data/d_and_i_sentences_de.csv")
# list of "d_and_i_words word" sentences
terms_d_and_i_words = list(df_d_and_i_words_sentences["Lemma"])

#load communal coded terms
df_communal_words = pd.read_csv("training_data/communal_language_DE.csv")

# load agentic language
df_agentic_words_en = pd.read_csv("training_data/agentic_language_EN.csv")

# dictionaries to handle false positives
false_positive_agentic = ["selbst", "flexible", "Probleme", "unabhängig", "Entwickler"]
false_positive_empty = ["international"]
exceptions = ["Unternehmen", "Firma", "Gruppe", "Gesellschaft", "Kollektivgesellschaft", "Team", "Organization", "Gliederung"]
terms_false_positive = genderdenom_false_positives["False_positives"].tolist()

app.mount("/static", StaticFiles(directory="static"), name="static")

app.mount("/files", StaticFiles(directory="files"), name="files")

templates = Jinja2Templates(directory="templates")

def get_current_username(credentials: Optional[HTTPBasicCredentials] = Depends(security)):
    # Credentials are missing
    if credentials is None:
        # Auth is disabled, just proceed
        if basic_auth["enabled"] == "false":
            return "anon"
       # Auth is enabled, raise 401
        else:
           raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Basic"},
        )

    # Verify the credentials as usual
    if (basic_auth["username"] is None or basic_auth["password"] is None):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Incorrect user configuration",
        )

    correct_username = secrets.compare_digest(credentials.username, basic_auth["username"])
    correct_password = secrets.compare_digest(credentials.password, basic_auth["password"])
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username

@app.get("/")
def get_root():
    return RedirectResponse(url='/form', status_code=301)

@app.get("/lt")
def get_root():
    return languagetool_url

@app.get("/docs", include_in_schema=False)
def get_swagger_documentation(username: str = Depends(get_current_username)):
    return get_swagger_ui_html(openapi_url="/openapi.json", title="docs")

@app.get("/openapi.json", include_in_schema=False)
def openapi(username: str = Depends(get_current_username)):
    return get_openapi(title=app.title, version=app.version, routes=app.routes)

@app.get("/form", response_class=HTMLResponse)
def form(request: Request):
    return templates.TemplateResponse("form.html", {"request": request})

@app.get("/categories")
def get_categories(lang: LangType = "de"):
    return categories_with_labels[lang]

@app.post("/serialize", response_class=PlainTextResponse)
def serialize(user_request_in: RequestIn):
    data =  serialize_log_data(user_request_in, ResultsOut([], "en"))
    return data

@app.post("/log", status_code=201)
def log(user_request_in: RequestInEvent, background_tasks: BackgroundTasks):
    set_sentry_context(user_request_in)

    background_tasks.add_task(log_response, user_request_in)

@app.post("/check", response_model=ResultsOut)
async def check_query(user_request_in: RequestIn, background_tasks: BackgroundTasks):
    set_sentry_context(user_request_in)

    languagetools_results, lang = await languagetool_rules(user_request_in)

    language_rules_results = language_rules(user_request_in, lang)

    list_results = languagetools_results + language_rules_results

    response = ResultsOut.factory(list_results, lang)

    background_tasks.add_task(log_response, user_request_in, response)

    return response

# Functions
def set_sentry_context(user_request_in: RequestIn):
    sentry_sdk.set_context("user", {"id": user_request_in.id})

async def languagetool_rules(user_request_in: RequestIn):
    list_results = []

    async with aiohttp.ClientSession() as session:
        langs = ["en", "de", "auto"]

        payload = {
            "text": user_request_in.text,
            "language": user_request_in.lang,
            "motherTongue": user_request_in.config.primary_language
        }

        if user_request_in.lang == "auto":
            payload["preferredLanguages"] = user_request_in.config.preferred_languages
            payload["preferredVariants"] = user_request_in.config.preferred_variants

        async with session.post(languagetool_url + "/check", data=payload) as r:
            assert r.status == 200
            result = await r.json()

            if "language" not in result:
                lang = None
            if result["language"]["code"][0:2] not in langs:
                lang = None
            elif "matches" in result:
                lang = Lang(result["language"]["code"])

                if "orthography" not in user_request_in.config.disabled_categories:
                    for match in result["matches"]:
                        offset = int(match["offset"])
                        end = offset + int(match["length"])
                        alternatives = []
                        if "replacements" in match:
                            for replacement in match["replacements"]:
                                value = replacement["value"]
                                value = value if value != "" else "-"
                                alternatives.append(value)

                        list_results.append(
                            ResultOut.factory(
                                user_request_in.config,
                                lang,
                                user_request_in.text[offset:end],
                                "orthography",
                                offset,
                                end,
                                alternatives,
                                None,
                                match["shortMessage"],
                                None,
                                match["message"]
                            )
                        )

    if isinstance(lang, Lang) != True:
        raise HTTPException(status_code=400, detail="Language could not be determined")

    return list_results, lang

def language_rules(user_request_in: RequestIn, lang: Lang):
    #apply SpaCy pre-built model
    tokens = model[lang.locale](user_request_in.text)
    
    #Phrase matcher part to handle False positives with two words and special simbols
    matcher = PhraseMatcher(model[lang.locale].vocab)

    # Only run model.make_doc to speed things up
    patterns = [model[lang.locale].make_doc(user_request_in.text) for value in terms_false_positive]
    matcher.add("TerminologyList", patterns)
    
    #functions for German rules
    if lang.locale == "de":
        list_results = GermanRules(lang, tokens, user_request_in)

    #function for English rules
    elif lang.locale == "en":
        list_results = EnglishRules(lang, tokens, user_request_in)

    else:
        list_results = []
    
    return list_results

def serialize_log_data(user_request_in: RequestIn, response: ResultsOut = None):
    if response is None:
        data = {
            "event": jsonable_encoder(user_request_in),
        }
    else:
        data = {
            "request": jsonable_encoder(user_request_in),
            "response": jsonable_encoder(response),
        }

    return json.dumps(data)

def log_response(user_request_in: RequestIn, response: ResultsOut = None):
    if user_request_in.id is None or logging_enabled is None:
        return

    data = serialize_log_data(user_request_in, response)
    dirname = os.getcwd() + '/logs/' + user_request_in.id
    filename = dirname + '/' + datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] + '.json'

    os.makedirs(os.path.dirname(filename), exist_ok=True)
    f = open(filename, 'w')
    f.write(data)

#Function for all German rules
def GermanRules(lang, tokens, user_request_in: RequestIn):
    list_full = []

    #Agentic language and related false positives catch
    if "agentic_language" not in user_request_in.config.disabled_categories:
        list_full+= AgenticLanguageAnalysis(user_request_in.config, lang, tokens, df_agentic_ct)

    # Empty words&sentences catch
    if "empty_words" not in user_request_in.config.disabled_categories:
        list_full+= EmptyWordAnalysis(user_request_in.config, lang, tokens, terms_empty, df_empty_word, df_empty_sentences)

    if "gendered_denominations" not in user_request_in.config.disabled_categories:
        list_full+= GenderedDenomEnd(user_request_in.config, lang, user_request_in.text)
        list_full+= GenderedDenomAnalysis(user_request_in.config, lang, tokens, df_gender_ct)
    
    #discriminating words catch
    if "biased_language" not in user_request_in.config.disabled_categories:
        list_full+= RulesBased(user_request_in.config, lang, tokens, df_discrim_words, "biased_language")
    
    #communal terms
    if "communal_language" not in user_request_in.config.disabled_categories:
        list_full+= RulesBased(user_request_in.config, lang, tokens, df_communal_words, "communal_language")

    #d_and_i_words words
    if "d_and_i_words" not in user_request_in.config.disabled_categories:
        list_full+= RulesBasedWordsPhraseMatcher(user_request_in.config, lang, tokens, terms_d_and_i_words, df_d_and_i_words, "d_and_i_words")

    # Empty words&sentences catch
    if "empty_words" not in user_request_in.config.disabled_categories:
        list_full+= EmptyWordAnalysis(user_request_in.config, lang, tokens, terms_empty, df_empty_word, df_empty_sentences)

    # boasting words&sentences catch
    if "boasting_words" not in user_request_in.config.disabled_categories:
        list_full+= BoastingWordsSentences(user_request_in.config, lang, tokens, df_boast_word, df_boast_sentences)

    return list_full

#Function for all English rules
def EnglishRules(lang, tokens, user_request_in: RequestIn):
    list_full = []

    if "agentic_language" not in user_request_in.config.disabled_categories:
        list_full+= RulesBasedEN(user_request_in.config, lang, tokens, df_agentic_words_en, "agentic_language")
    
    return list_full

"""Function to catch the words related to False Positive in the user query"""
def IsItFalsePositive(word, false_positive):
    for item in false_positive:
        if word == item:
            return True

    return False

"""Function to catch ending in German Denom"""
def GenderedDenomEnd(config: Config, lang, text):
    category = "gendered_roles"      
    subcategory = "gendered_denominations_ending"
 
    list_ending = []
    for item in config._gendereddenom_ending:
        if config.german_gender_ending == item:
            continue
        span = re.search(config._gendereddenom_ending[item], text)
        if type(span)== re.Match:
            list_ending.append(ResultOut.factory(
                config,
                lang,
                item,
                category,
                span.start(),
                span.end(),
                [config.german_gender_ending],
                subcategory)
             )   

    return list_ending

"""Function to handle dependecies of the adjectives."""
# this function agentic language & related false positives
def AgenticLanguageAnalysis(config: Config, lang, tokens, df):
    category = "agentic_language"
    list_tokens = []
    dic_anc = {} 
    list_false_positives = []    

    for token in tokens:
        #check if the user query have false positives
        if IsItFalsePositive(token.lemma_, false_positive_agentic):
            #recognise if there is Name of organisation or geographical name in the query
            for entity in tokens.ents:
                if entity.label_ == "ORG":
                    list_false_positives.append({
                        "false positives": token.text,
                        "category": "agentic_language"                    
                    })

            # check if the word is adverb
            if token.pos_ =="ADV":
                list_false_positives.append({
                    "false positives": token.text,
                    "category": "agentic_language"
                })
                
            # check if the word is adjective and find out how it depends on the other words to feel the contex
            elif token.pos_ == "ADJ":# or token.tag_== "ADJD":
                dic_anc[token.lemma_] = list(token.ancestors)
                for key in dic_anc.keys():
                    if key in false_positive_agentic:
                        for item in dic_anc[key]:
                            if item.text in exceptions:
                                list_false_positives.append({
                                    "false positives": token.text,
                                    "category": "agentic_language"
                                })
        else:
            for word, alternative in zip(df["Lemma"], df["Alternatives_split_company"]):
                if token.lemma_ == word:
                    list_tokens.append(
                        ResultOut.factory(
                            config, 
                            lang,
                            token.text,
                            category,
                            token.idx,
                            None,
                            ast.literal_eval(alternative)
                        )
                    )


    return list_tokens     
    
def GenderedDenomAnalysis(config: Config, lang, tokens, df):
    category = "gendered_roles"      
    subcategory = "gendered_denominations"      
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
            for word, alternative_sing, alternative_plur in zip(df["Lemma"], df["Alternative_Singular_split"], df["Alternative_Plural_split"]):
                if token.lemma_ == word:
                    if token.morph.get("Number")[0]=="Sing":
                        list_tokens.append(
                            ResultOut.factory(
                                config, 
                                lang,
                                token.text,
                                category,
                                token.idx,
                                None,
                                ast.literal_eval(alternative_sing),
                                subcategory
                            )
                        )
               
                    elif token.morph.get("Number")[0]=="Plur":
                        list_tokens.append(
                            ResultOut.factory(
                                config,
                                lang,
                                token.text,
                                category,
                                token.idx,
                                None,
                                ast.literal_eval(alternative_plur)
                            )
                        )
             

    else:
        for token in tokens:
            for word, alternative_sing, alternative_plur in zip(df["Lemma"], df["Alternative_Singular_split"], df["Alternative_Plural_split"]):
                if token.lemma_ == word:
                    if token.morph.get("Number")[0]=="Sing":
                        list_tokens.append(
                            ResultOut.factory(
                                config,
                                lang,
                                token.text,
                                category,
                                token.idx,
                                None,
                                ast.literal_eval(alternative_sing)
                            )
                        )
               
                    elif token.morph.get("Number")[0]=="Plur":
                        list_tokens.append(
                            ResultOut.factory(
                                config,
                                lang,
                                token.text,
                                category,
                                token.idx,
                                None,
                                ast.literal_eval(alternative_plur)
                            )
                        )
                            
              

    return list_tokens

# Boasting words and sentences analisys function, shows alternatives if avalible
def BoastingWordsSentences(config: Config, lang, tokens, df, df_sentences):
    category = "boasting_words"
    list_tokens = []
    #Phrase matcher part to handle False positives with two words and special simbols
    matcher = PhraseMatcher(model[lang.locale].vocab)

     # Only run model.make_doc to speed things up
    patterns = [model[lang.locale].make_doc(text) for text in terms_boast]
    matcher.add("TerminologyList", patterns)

    for token in tokens:
        for word, alternative in zip(df["Lemma"], df["Alternatives"]):
            if token.lemma_ == word:
                list_tokens.append(
                    ResultOut.factory(
                        config,
                        lang,
                        token.text,
                        category,
                        token.idx,
                        None,
                        ast.literal_eval(alternative)
                    )
                )  

    
    matches = matcher(tokens)
    for match_id, start, end in matches:
        for sentence, alternative in zip(df_sentences["Lemma"], df_sentences["Alternatives"]):
            span = tokens[start:end]
            if span.text == sentence:
                list_tokens.append(
                    ResultOut.factory(
                        config,
                        lang, 
                        span.text,
                        category,
                        span.start_char,
                        span.end_char,
                        ast.literal_eval(alternative)
                    )
                )

    return list_tokens 

# Unified function for Emty words false positives and rules    
def EmptyWordAnalysis(config: Config, lang, tokens, terms, df, df_sentence):
    #category = df_empty_sentences(["subcategory"])
    category = "empty_words"
    list_tokens = []
    list_false_positives = []
    #Phrase matcher part to handle False positives with two words and special simbols
    matcher = PhraseMatcher(model[lang.locale].vocab)

     # Only run model.make_doc to speed things up
    patterns = [model[lang.locale].make_doc(text) for text in terms]
    matcher.add("TerminologyList", patterns)

    for i in range(len(tokens))[1:-1]:
        #check if the user query have false positives
        if IsItFalsePositive(tokens[i].lemma_, false_positive_empty):
            #recognise if there is Name of organisation or geographical name in the query
            if len(tokens.ents) > 0:
                #this output will be deleted in production
                list_false_positives.append({
                    "false positives": tokens[i].text,    
                    "category": "EmptyWord"                  
                })
            else:
                for word, alternative in zip(df["Lemma"], df["Alternative_Singular_split"]):
                    if len(alternative) >5:
                        if tokens[i].lemma_ == word:
                            list_tokens.append(
                                ResultOut.factory(
                                    config,
                                    lang,
                                    tokens[i].text,
                                    category,
                                    tokens[i].idx,
                                    tokens[i].idx+len(tokens[i].text),
                                    ast.literal_eval(alternative)
                                )
                            )    
                    else:
                        if tokens[i].lemma_ == word:
                            if tokens[i-1].is_stop == True or tokens[i-1].is_punct==True:
                                list_tokens.append(
                                    ResultOut.factory(
                                        config,
                                        lang,
                                        tokens[i-1:i+1].text,
                                        category,
                                        tokens[i-1].idx,
                                        tokens[i-1].idx+len(tokens[i-1:i+1].text),
                                        ["-"]
                                    )
                                )
                            else:
                                list_tokens.append(
                                    ResultOut.factory(
                                        config,
                                        lang,
                                        tokens[i].text,
                                        category,
                                        tokens[i].idx,
                                        tokens[i].idx+len(tokens[i].text),
                                        ["-"]
                                    )
                                )
                            
        else:
            for word, alternative in zip(df["Lemma"], df["Alternative_Singular_split"]):
                    if len(alternative) >5:
                        if tokens[i].lemma_ == word:
                            list_tokens.append(
                                ResultOut.factory(
                                    config,
                                    lang,
                                    tokens[i].text,
                                    category,
                                    tokens[i].idx,
                                    tokens[i].idx+len(tokens[i].text),
                                    ast.literal_eval(alternative)
                                )
                            )    
                    else:
                        if tokens[i].lemma_ == word:
                            if tokens[i-1].is_stop == True or tokens[i-1].is_punct==True:
                                list_tokens.append(
                                    ResultOut.factory(
                                        config,
                                        lang,
                                        tokens[i-1:i+1].text,
                                        category,
                                        tokens[i-1].idx,
                                        tokens[i-1].idx+len(tokens[i-1:i+1].text),
                                        ["-"]
                                    )
                                )
                            else:
                                list_tokens.append(
                                    ResultOut.factory(
                                        config,
                                        lang,
                                        tokens[i].text,
                                        category,
                                        tokens[i].idx,
                                        tokens[i].idx+len(tokens[i].text),
                                        ["-"]
                                    )
                                )
 
    matches = matcher(tokens)
    for match_id, start, end in matches:
        for sentence, alternative in zip(df_sentence["Lemma"], df_sentence["Alternative_Singular_split"]):
            span = tokens[start:end]
            if span.text == sentence:
                list_tokens.append(
                    ResultOut.factory(
                        config,
                        lang,
                        span.text,
                        category,
                        span.start_char,
                        span.end_char,
                        ast.literal_eval(alternative) 
                    )
                )

    return list_tokens 

# Unified function for rules and sentence false positives   
def RulesBasedWordsPhraseMatcher(config: Config, lang, tokens, terms, df, category):
    list_tokens = []
    #Phrase matcher part to handle False positives with two words and special simbols
    matcher = PhraseMatcher(model[lang.locale].vocab)

     # Only run model.make_doc to speed things up
    patterns = [model[lang.locale].make_doc(text) for text in terms]
    matcher.add("TerminologyList", patterns)

    for token in tokens:
        for index, row in df.iterrows():
            if token.lemma_ == row["Lemma"]:
                list_tokens.append(
                    ResultOut.factory(
                        config,
                        lang,
                        token.text,
                        category,
                        token.idx
                    )
                )
    
    matches = matcher(tokens)
    for match_id, start, end in matches:
        span = tokens[start:end]
        list_tokens.append(
            ResultOut.factory(
                config,
                lang,
                span.text,
                category,
                span.start_char,
                span.end_char
            )
        )

    return list_tokens 

#Unified function for rules
def RulesBased(config: Config, lang, tokens, df, category):
    list_tokens = []
    for token in tokens:
        for word in list(df["Lemma"]):
            if token.lemma_ == word:
                list_tokens.append(
                    ResultOut.factory(
                        config,
                        lang,
                        token.text,
                        category,
                        token.idx
                    )
                )

    return list_tokens 

# Deutshe Bahn realated rule. Function to catch masculine words in sentences like 
# Deutshe Bahn als.. Deutshe Bahn ist..
def DB_Fem(tokens):
    
    category = "DB_grammatic"
    db_match_list = []
    matcher_db = Matcher(model[lang.locale].vocab)
    # Add match ID "DB" with no callback and one pattern
    pattern_db = [{"TEXT": "Deutsche"}, {"TEXT": "Bahn"}, {"LEMMA": "sein", "OP": "*"}, {"POS": "ADV", "OP": "*"}, {"TEXT": "als", "OP": "*"}, {"TAG": "ART", "OP": "*"}, {"POS": "ADJ", "OP": "*"}, {'POS': 'NOUN', "MORPH": {'IS_SUPERSET': ["Gender=Masc"]}}]
    #use greedy = "LONGEST" to find all matches in the text related to pattern
    matcher_db.add("DB", [pattern_db], greedy = "LONGEST")
    matches_db = matcher_db(tokens)
    
    for match_id, start, end in matches_db:
        string_id = model.vocab.strings[match_id]  # Get string representation
        span = doc[start:end]  # The matched span
        db_match_list.append(
            ResultOut.factory(
                config,
                lang,
                span.text,
                category,
                span.start_char,
                span.end_char
            )
        )
    return db_match_list
    

    
    

#function to catch ending in gendered denom
#Rules based english function
def RulesBasedEN(config: Config, lang, tokens, df, category):
    list_tokens = []
    
    for token in tokens:
        for word in list(df["Lemma"]):
            if token.lemma_ == word:
                list_tokens.append(
                    ResultOut.factory(
                        config,
                        lang,
                        token.text,
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
