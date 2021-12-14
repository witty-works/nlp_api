import platformshconfig
from app.models import (
    Config,
    LangType,
    Lang,
    RequestIn,
    RequestInEvent,
    ResultOut,
    ResultsOut,
    ConfRequest,
)
import ast

import re
from spacy.tokens import Doc
from spacy.matcher import PhraseMatcher, Matcher
import spacy
import pandas as pd
from datetime import datetime
import uvicorn
import os
import json
import base64
import secrets
import aiohttp
import copy
from functools import lru_cache

from fastapi import (
    FastAPI,
    Request,
    HTTPException,
    BackgroundTasks,
    Depends,
    status,
)

from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

from fastapi.security import HTTPBasic, HTTPBasicCredentials

from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import RedirectResponse, PlainTextResponse, FileResponse

from fastapi.exception_handlers import (
    http_exception_handler,
)

from typing import List, Optional
from pydantic import BaseSettings
from app.categories import categories

import logging

from redis import Redis
import platformshconfig
from fakeredis import FakeStrictRedis

import posthog


class Settings(BaseSettings):
    """Load environment variables to python objects using pydantic."""

    logging_enabled: bool = False
    logging_config_filename: str = "./logs/error.log"
    logging_config_level: str = "ERROR"
    training_data_enabled: bool = False
    platform_environment: str = "local"
    languagetool_api: Optional[str]
    languagetool_verify_ssl: bool = True
    platform_relationships: Optional[str]
    api_docs_username: Optional[str]
    api_docs_password: Optional[str]
    api_docs_auth_enabled: bool = False
    instrumentation_key: str = ""
    testing: bool = False
    read_rules_from_redis: bool = False
    posthog_api_key: Optional[str]
    posthog_host: Optional[str]
    posthog_ids: List[str] = []

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings():
    return Settings()


settings = get_settings()

# Logging set up
@lru_cache()
def set_up_logger():
    logging.basicConfig(level=settings.logging_config_level)
    logging.getLogger().handlers.clear()
    formatter = logging.Formatter("[%(asctime)s] %(name)s %(levelname)s - %(message)s")

    if settings.logging_enabled:
        if settings.instrumentation_key:
            from opencensus.ext.azure.log_exporter import AzureLogHandler

            ah = AzureLogHandler(
                connection_string="InstrumentationKey={}".format(
                    settings.instrumentation_key
                )
            )
            ah.setFormatter(formatter)
            logging.getLogger().addHandler(ah)
        else:
            filename = os.path.abspath(settings.logging_config_filename)
            os.makedirs(os.path.dirname(filename), exist_ok=True)
            fh = logging.FileHandler(filename=filename)
            fh.setFormatter(formatter)
            logging.getLogger().addHandler(fh)
    else:
        logging.getLogger().addHandler(logging.NullHandler())


set_up_logger()
logging.debug("app started with settings: %s", settings)


@lru_cache()
def setup_posthog():
    if not settings.training_data_enabled:
        return

    posthog.api_key = settings.posthog_api_key
    posthog.host = settings.posthog_host

    if settings.logging_enabled:
        posthog.debug = True

    if settings.testing:
        posthog.disabled = True


setup_posthog()

# Languagetool URL
@lru_cache()
def get_languagetool_url():
    if settings.languagetool_api:
        return settings.languagetool_api

    if settings.platform_relationships:
        relationships = json.loads(base64.b64decode(settings.platform_relationships))
        languagetool = relationships["languagetool"][0]
        return "%(scheme)s://%(host)s:%(port)d/v2" % languagetool

    return "https://lt.default.api.witty.works/v2"


languagetool_url = get_languagetool_url()

# Regular expression library
# convert string of list into list of the strings
# project models

version = "1.7.3"

app = FastAPI(
    title="Witty NLP API",
    version=version,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# To catch raised `HTTPException` exceptions as per:
# https://fastapi.tiangolo.com/tutorial/handling-errors/
# Might have to add something similar for `RequestValidationError`


@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request, e):
    if e.status_code >= 500:
        logging.exception("Exception logging message")

    return await http_exception_handler(request, e)


security = HTTPBasic(auto_error=False)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

categories_with_labels = {}
languages = ["en", "de"]
for language in languages:
    lang = Lang(language)
    categories_with_labels[language] = copy.deepcopy(categories)
    for category in categories_with_labels[language]:
        categories_with_labels[language][category]["label"] = lang._(
            "rules." + category + "_label"
        )

# Model data
model = {"en": spacy.load("en_core_web_sm"), "de": spacy.load("de_core_news_sm")}
# custom lematizer to correct the lemmas in spacy library, to add to the curent spacy lematizer
dict_lemma_lookup = {
    "international": "international",
    "internationale": "international",
    "Meister": "Meister",
    "kämpfend": "kämpfend",
    "abgebrüht": "abgebrüht",
    "beherrschend": "beherrschend",
    "entscheidend": "entscheidend",
    "entschlossen": "entschlossen",
    "angewiesen": "angewiesen",
    "berührt": "berührt",
    "besonnen": "besonnen",
    "betreut": "betreut",
    "bewegt": "bewegt",
    "einfühlend": "einfühlend",
    "engagiert": "engagiert",
    "entgegenkommend": "entgegenkommend",
    "ergreifend": "ergreifend",
    "fördernd": "fördernd",
    "gerührt": "gerührt",
    "heiter": "heiter",
    "lieb": "lieb",
    "mitfühlend": "mitfühlend",
    "mitwirkend": "mitwirkend",
    "motiviert": "motiviert",
    "nährend": "nährend",
    "teilnehmend": "teilnehmend",
    "unterstützend": "unterstützend",
    "verbindend": "verbindend",
    "vermittelnd": "vermittelnd",
    "vertraut": "vertraut",
    "weich": "weich",
    "zusammenhängend": "zusammenhängend",
    "zusammenwirkend": "zusammenwirkend",
    "zustimmend": "zustimmend",
    "jünger": "jünger",
    "ausgeprägt": "ausgeprägt",
    "ausgezeichnet": "ausgezeichnet",
    "äußerst": "äußerst",
    "beeindruckend": "beeindruckend",
    "beste": "beste",
    "bester": "beste",
    "besten": "beste",
    "bestem": "beste",
    "bestes": "beste",
    "etabliert": "etabliert",
    "führend": "führend",
    "fundiert": "fundiert",
    "gewandt": "gewandt",
    "Götter": "Götter",
    "hervorragend": "hervorragend",
    "überzeugend": "überzeugend",
    "zwingend": "zwingend",
}

lookup_table = model["de"].get_pipe("lemmatizer").lookups.get_table("lemma_lookup")
for key in dict_lemma_lookup:
    lookup_table.set(key, dict_lemma_lookup[key])

# load agentic language
df_agentic_ct = pd.read_csv("training_data/agentic_DE.csv")
# list_agentic = list(df_agentic_ct["Lemma"])

# load Gender denom_de
df_gender_ct = pd.read_csv("training_data/GenderedNoun_DE.csv")
# load Gender denom_de false_positives
genderdenom_false_positives = pd.read_csv("training_data/titles_false_positives_DE.csv")

# load discriminating words_de
df_discrim_words = pd.read_csv("training_data/unconscious_bias_DE.csv")

# load style words_de
df_style_word = pd.read_csv("training_data/style_words_DE.csv")
df_style_sentences = pd.read_csv("training_data/style_sentences_DE.csv")
# list of "hollow word" sentences
terms_style = list(df_style_sentences["Lemma"])

# load Exaggerating word and sentences de
df_exaggerating = pd.read_csv("training_data/exaggerating_words_DE.csv")
df_exaggerating_sentences = pd.read_csv("training_data/exaggerating_sentences_DE.csv")
# list of "exaggerating word" sentences
terms_exaggerating = list(df_exaggerating_sentences["Lemma"])

# load inslusive words
df_d_and_i_words = pd.read_csv("training_data/d_and_i_words_DE.csv")
# load inslusive sentences
df_d_and_i_words_sentences = pd.read_csv("training_data/d_and_i_sentences_DE.csv")
# list of "d_and_i_words word" sentences
terms_d_and_i_words = list(df_d_and_i_words_sentences["Lemma"])

# load communal coded terms
df_communal_words = pd.read_csv("training_data/communal_DE.csv")

# English
# load agentic language
df_agentic_words_en = pd.read_csv("training_data/agentic_EN.csv")

# load openly discriminating words
df_open_dis_word_en = pd.read_csv("training_data/open_dis_words_EN.csv")
df_open_dis_sentence_en = pd.read_csv("training_data/open_dis_sentences_EN.csv")

# load inclusive language
df_inclusive_word_en = pd.read_csv("training_data/inclusive_words_EN.csv")
df_inclusive_sentence_en = pd.read_csv("training_data/inclusive_sentences_EN.csv")

# load style words
df_style_word_en = pd.read_csv("training_data/style_words_EN.csv")
df_style_sentence_en = pd.read_csv("training_data/style_sentences_EN.csv")

# dictionaries to handle false positives
false_positive_agentic = ["selbst", "flexible", "Probleme", "unabhängig", "Entwickler"]
false_positive_style = ["international"]
exceptions = [
    "Unternehmen",
    "Firma",
    "Gruppe",
    "Gesellschaft",
    "Kollektivgesellschaft",
    "Team",
    "Organization",
    "Gliederung",
]
gender_false_positive = genderdenom_false_positives["False_positives"].tolist()


@app.get("/companyRules")
async def get_redis(user: str):
    try:
        keys = redis.keys("*")
        for key in keys:
            user_list = json.loads(redis.get(key))["users"]
            if user in user_list:
                return json.loads(redis.get(key))
    except Exception as e:
        return e


# corporate false positive DB
corporate_false_positive = [
    "stark",
    "starke",
    "starkes",
    "starker",
    "Führungskraft",
    "Führungskräfte",
    "Führungskräften",
]
terms_false_positive = gender_false_positive + corporate_false_positive
false_positive_agentic += corporate_false_positive

# read redis configuration

if settings.testing == True:
    redis = FakeStrictRedis()
else:
    platform_config = platformshconfig.Config()
    if platform_config.is_valid_platform():
        redis_credentials = platform_config.credentials("rediscache")
        redis = Redis(redis_credentials["host"], redis_credentials["port"])


app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")


def get_current_username(
    credentials: Optional[HTTPBasicCredentials] = Depends(security),
):
    # Credentials are missing
    if credentials is None:
        # Auth is disabled, just proceed
        if not settings.api_docs_auth_enabled:
            return "anon"

        # Auth is enabled, raise 401
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Basic"},
        )

    # Verify the credentials as usual
    if settings.api_docs_username is None or settings.api_docs_password is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Incorrect user configuration",
        )

    correct_username = secrets.compare_digest(
        credentials.username, settings.api_docs_username
    )
    correct_password = secrets.compare_digest(
        credentials.password, settings.api_docs_password
    )
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username


@app.get("/")
def get_root():
    return RedirectResponse(url="/form", status_code=301)


@app.get("/exception")
def raise_exception(
    exception_type: str = None,
    status_code: int = 500,
    username: str = Depends(get_current_username),
):
    if exception_type == "http":
        raise HTTPException(status_code=status_code)

    raise Exception("Example exception")


@app.get("/lt")
def get_lt(username: str = Depends(get_current_username)):
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
def serialize(
    user_request_in: RequestIn, username: str = Depends(get_current_username)
):
    data = collect_user_training_data(user_request_in, ResultsOut([], "en"))
    return json.dumps(data)


@app.post("/log", status_code=201)
def log(
    request: Request, user_request_in: RequestInEvent, background_tasks: BackgroundTasks
):
    background_tasks.add_task(write_user_training_data, request, user_request_in)


@app.post("/check", response_model=ResultsOut)
async def check_query(
    request: Request, user_request_in: RequestIn, background_tasks: BackgroundTasks
):
    if settings.read_rules_from_redis:
        await set_rules(user_request_in)

    languagetools_results, lang = await languagetool_rules(user_request_in)

    language_rules_results = language_rules(user_request_in, lang)

    list_results = languagetools_results + language_rules_results

    response = ResultsOut.factory(list_results, lang)

    background_tasks.add_task(
        write_user_training_data, request, user_request_in, response
    )

    return response


@app.post("/storeRules")
async def store_redis(corporate_rules: ConfRequest):
    try:
        company_object = {
            "users": corporate_rules.users,
            "config": {
                "forced": dict(corporate_rules.forced),
                "suggestion": dict(corporate_rules.suggestion),
            },
        }

        # Set a value
        redis.set(str(corporate_rules.company), json.dumps(company_object))
    except Exception as e:
        return e
    return company_object


# Functions


async def set_rules(user_request_in: RequestIn):
    general_config = Config()
    corporate_rules = await get_redis(user_request_in.id)
    if corporate_rules and type(corporate_rules) is dict:
        user_rules = user_request_in.config.__dict__
        forced_config = corporate_rules["config"]["forced"]
        default_config = corporate_rules["config"]["suggestion"]
        forced_filtered = {
            k: v
            for (k, v) in forced_config.items()
            if v != "" and v is not None and v != []
        }
        default_filtered = {
            k: v
            for (k, v) in default_config.items()
            if v != "" and v is not None and v != []
        }
        company_config = {**default_filtered, **forced_filtered}

        for config_value in vars(general_config):
            # user set a value (change, if user not give a key)
            if user_rules[config_value] is not None:

                # company set a value and user can't change it
                if config_value in company_config and config_value in forced_filtered:
                    # overwrite user value
                    setattr(
                        user_request_in.config,
                        config_value,
                        forced_config[config_value],
                    )
                # company set a value on default, user can change it
                elif (
                    config_value in company_config and config_value in default_filtered
                ):
                    # set user value
                    setattr(
                        user_request_in.config, config_value, user_rules[config_value]
                    )
                else:
                    # company does not set a value, user can set a value
                    setattr(
                        user_request_in.config, config_value, user_rules[config_value]
                    )
            else:
                # user does not set a value, but company did
                if config_value in company_config:
                    setattr(
                        user_request_in.config,
                        config_value,
                        company_config[config_value],
                    )


async def languagetool_rules(user_request_in: RequestIn):
    list_results = []

    async with aiohttp.ClientSession(
        connector=aiohttp.TCPConnector(verify_ssl=settings.languagetool_verify_ssl)
    ) as session:
        langs = ["en", "de", "auto"]

        payload = {
            "text": user_request_in.text,
            "language": user_request_in.lang,
            "motherTongue": user_request_in.config.primary_language,
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
                german_gender_ending = user_request_in.config.german_gender_ending

                if "orthography" not in user_request_in.config.disabled_categories:
                    for match in result["matches"]:
                        offset = int(match["offset"])
                        end = offset + int(match["length"])
                        if (
                            german_gender_ending
                            == user_request_in.text[
                                end : end + len(german_gender_ending)
                            ]
                        ):
                            continue

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
                                user_request_in.text,
                                "orthography",
                                "orthography",
                                offset,
                                end,
                                alternatives,
                                match["shortMessage"],
                                None,
                                match["message"],
                            )
                        )

    if isinstance(lang, Lang) != True:
        raise HTTPException(status_code=400, detail="Language could not be determined")

    return list_results, lang


def language_rules(user_request_in: RequestIn, lang: Lang):
    # apply SpaCy pre-built model
    tokens = model[lang.locale](user_request_in.text)

    # functions for German rules
    if lang.locale == "de":
        list_results = GermanRules(lang, tokens, user_request_in)

    # function for English rules
    elif lang.locale == "en":
        list_results = EnglishRules(lang, tokens, user_request_in)

    else:
        list_results = []

    return list_results


def clean_event_data(user_request_in: RequestIn):
    data = user_request_in.dict()

    return data


def clean_request_data(request: Request, user_request_in: RequestIn):
    data = user_request_in.dict(exclude={"text"})
    data["text"] = {
        "length": len(user_request_in.text),
    }
    data["user_agent"] = request.headers.get("user-agent")
    data["origin"] = request.headers.get("origin")

    return data


def clean_response_data(response: ResultsOut):
    data = response.dict(exclude={"results": {"__all__": {"context"}}})

    return data


def collect_user_training_data(
    request: Request, user_request_in: RequestIn, response: ResultsOut = None
):
    if response is None:
        data = {
            "event": clean_event_data(user_request_in),
        }
    else:
        data = {
            "request": clean_request_data(request, user_request_in),
            "response": clean_response_data(response),
        }

    return data


def write_user_training_data(
    request: Request, user_request_in: RequestIn, response: ResultsOut = None
):
    if user_request_in.id is None or not settings.training_data_enabled:
        return

    data = collect_user_training_data(request, user_request_in, response)

    if user_request_in.id in settings.posthog_ids:
        posthog.capture(user_request_in.id, user_request_in.type, data)
    else:
        date = datetime.utcnow().strftime("%Y-%m-%d")

        dirname = os.getcwd() + "/user_training_data/installs/" + user_request_in.id
        os.makedirs(dirname, exist_ok=True)

        dirname = os.getcwd() + "/user_training_data/" + date + "/" + user_request_in.id
        os.makedirs(dirname, exist_ok=True)

        filename = (
            dirname
            + "/"
            + datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            + ".json"
        )

        f = open(filename, "w")
        f.write(json.dumps(data))


# Function for all German rules


def IsNotNoun(pos):
    return pos != "NOUN" and pos != "PROPN" and pos != "PRON"


def GetNonNounLowerCased(token):
    token_word = token.lemma_
    if IsNotNoun(token.pos_):
        token_word = token_word.lower()

    return token_word


def GermanRules(lang, tokens, user_request_in: RequestIn):
    list_full = []

    # Agentic language and related false positives catch
    if "agentic" not in user_request_in.config.disabled_categories:
        list_full += AgenticLanguageAnalysis(
            user_request_in.config, lang, user_request_in.text, tokens, df_agentic_ct
        )

    if "gendered" not in user_request_in.config.disabled_categories:
        list_full += GenderedDenomAnalysis(
            user_request_in.config, lang, user_request_in.text, tokens, df_gender_ct
        )

    if "misgendered_institutions" not in user_request_in.config.disabled_categories:
        list_full += MisgenderingInstitutions(
            user_request_in.config, lang, user_request_in.text, tokens
        )

    if "gendered_denomination_ending" not in user_request_in.config.disabled_categories:
        list_full += GenderedDenomEnd(
            user_request_in.config, lang, user_request_in.text
        )

    # discriminating words catch
    if "unconscious_bias" not in user_request_in.config.disabled_categories:
        list_full += RulesBased(
            user_request_in.config,
            lang,
            user_request_in.text,
            tokens,
            df_discrim_words,
            "unconscious_bias",
            "unconscious_bias",
        )

    # communal terms
    if "communal" not in user_request_in.config.disabled_categories:
        list_full += RulesBased(
            user_request_in.config,
            lang,
            user_request_in.text,
            tokens,
            df_communal_words,
            "inclusive",
            "communal",
        )

    # d_and_i_words words
    if "d_and_i" not in user_request_in.config.disabled_categories:
        list_full += RulesBasedWordsPhraseMatcher(
            user_request_in.config,
            lang,
            user_request_in.text,
            tokens,
            terms_d_and_i_words,
            df_d_and_i_words,
            "inclusive",
            "d_and_i",
        )

    # style words&sentences catch
    if "style" not in user_request_in.config.disabled_categories:
        list_full += StyleWordAnalysis(
            user_request_in.config,
            lang,
            user_request_in.text,
            tokens,
            terms_style,
            df_style_word,
            df_style_sentences,
        )

    # exaggerating words&sentences catch
    if "exaggerating" not in user_request_in.config.disabled_categories:
        list_full += ExaggeratingWordsSentences(
            user_request_in.config,
            lang,
            user_request_in.text,
            tokens,
            df_exaggerating,
            df_exaggerating_sentences,
        )

    return list_full


# Function for all English rules


def EnglishRules(lang, tokens, user_request_in: RequestIn):
    list_full = []

    if "agentic" not in user_request_in.config.disabled_categories:
        list_full += RulesBasedEN(
            user_request_in.config,
            lang,
            user_request_in.text,
            tokens,
            df_agentic_words_en,
            "unconscious_bias",
            "agentic",
        )

    if "openly_discriminating" not in user_request_in.config.disabled_categories:
        list_full += RulesBasedWordsPhraseMatcherEN(
            user_request_in.config,
            lang,
            user_request_in.text,
            tokens,
            df_open_dis_word_en,
            df_open_dis_sentence_en,
            "openly_discriminating",
        )
    if "inclusive" not in user_request_in.config.disabled_categories:
        list_full += RulesBasedWordsPhraseMatcherNoAltEN(
            user_request_in.config,
            lang,
            user_request_in.text,
            tokens,
            df_inclusive_word_en,
            df_inclusive_sentence_en,
            "inclusive",
        )
    if "style" not in user_request_in.config.disabled_categories:
        list_full += RulesBasedWordsPhraseMatcherEN(
            user_request_in.config,
            lang,
            user_request_in.text,
            tokens,
            df_style_word_en,
            df_style_sentence_en,
            "style",
        )

    return list_full


"""Function to catch the words related to False Positive in the user query"""


def IsItFalsePositive(word, false_positive):
    for item in false_positive:
        if word == item:
            return True

    return False


"""Function to catch ending in German Denom"""


def GenderedDenomEnd(config: Config, lang, full_text):
    category = "gendered"
    subcategory = "gendered_denominations_ending"

    list_ending = []
    for item in config._gendereddenom_ending:
        if config.german_gender_ending == item:
            continue
        span = re.search(config._gendereddenom_ending[item], full_text)
        if type(span) == re.Match:
            list_ending.append(
                ResultOut.factory(
                    config,
                    lang,
                    item,
                    full_text,
                    category,
                    subcategory,
                    span.start(),
                    span.end(),
                    [config.german_gender_ending],
                )
            )

    return list_ending


"""Function to handle dependecies of the adjectives."""
# this function agentic language & related false positives


def AgenticLanguageAnalysis(config: Config, lang, full_text, tokens, df):
    category = "unconscious_bias"
    subcategory = "agentic"
    list_tokens = []
    dic_anc = {}
    list_false_positives = []

    for token in tokens:
        # check if the user query have false positives
        if IsItFalsePositive(token.lemma_, false_positive_agentic):
            # recognise if there is Name of organisation or geographical name in the query
            for entity in tokens.ents:
                if entity.label_ == "ORG":
                    list_false_positives.append(
                        {"false positives": token.text, "category": subcategory}
                    )

            # check if the word is adverb
            if token.pos_ == "ADV":
                list_false_positives.append(
                    {"false positives": token.text, "category": subcategory}
                )

            # check if the word is adjective and find out how it depends on the other words to feel the contex
            elif token.pos_ == "ADJ":  # or token.tag_== "ADJD":
                dic_anc[token.lemma_] = list(token.ancestors)
                for key in dic_anc.keys():
                    if key in false_positive_agentic:
                        for item in dic_anc[key]:
                            if item.text in exceptions:
                                list_false_positives.append(
                                    {
                                        "false positives": token.text,
                                        "category": subcategory,
                                    }
                                )
        else:
            for word, alternative in zip(df["Lemma"], df["Alternatives_split_company"]):
                if GetNonNounLowerCased(token) == word:
                    list_tokens.append(
                        ResultOut.factory(
                            config,
                            lang,
                            token.text,
                            full_text,
                            category,
                            subcategory,
                            token.idx,
                            None,
                            ast.literal_eval(alternative),
                        )
                    )

    return list_tokens


def GenderedDenomAnalysis(config: Config, lang, full_text, tokens, df):
    category = "gendered"

    list_tokens = []
    list_false_positives = []
    matcher = PhraseMatcher(model[lang.locale].vocab)

    # Only run model.make_doc to speed things up
    patterns = [model[lang.locale].make_doc(text) for text in terms_false_positive]
    matcher.add("TerminologyList", patterns)
    matches = matcher(tokens)

    old_start = 0

    rest_text = []

    if matches.__len__() != 0:
        for match_id, start, end in matches:
            span = tokens[start:end]
            list_false_positives.append({"False positives": span.text})
            part = tokens[old_start:start]

            rest_text.append(part.text)
            old_start = end

        docs = list(model[lang.locale].pipe(rest_text))
        c_doc = Doc.from_docs(docs)

        for i in range(len(c_doc)):
            for word, alternative_sing, alternative_plur, subcategory in zip(
                df["Lemma"],
                df["Sg_all_clean"],
                df["Pl_all_clean"],
                df["Primary_subcategory"],
            ):
                if c_doc[i].lemma_ == word:
                    if c_doc[i].morph.get("Number")[0] == "Sing":
                        list_tokens.append(
                            ResultOut.factory(
                                config,
                                lang,
                                c_doc[i].text,
                                full_text,
                                category,
                                subcategory,
                                c_doc[i].idx,
                                None,
                                ast.literal_eval(alternative_sing),
                            )
                        )
                        if c_doc[i - 1].text == "der":
                            list_tokens.append(
                                ResultOut.factory(
                                    config,
                                    lang,
                                    c_doc[i - 1].text,
                                    full_text,
                                    category,
                                    subcategory,
                                    c_doc[i - 1].idx,
                                    None,
                                    ["der~die"],
                                )
                            )
                        elif c_doc[i - 1].text == "einer":
                            list_tokens.append(
                                ResultOut.factory(
                                    config,
                                    lang,
                                    c_doc[i - 1].text,
                                    full_text,
                                    category,
                                    subcategory,
                                    c_doc[i - 1].idx,
                                    None,
                                    ["einer~eine"],
                                )
                            )
                    elif c_doc[i].morph.get("Number")[0] == "Plur":
                        list_tokens.append(
                            ResultOut.factory(
                                config,
                                lang,
                                c_doc[i].text,
                                full_text,
                                category,
                                subcategory,
                                c_doc[i].idx,
                                None,
                                ast.literal_eval(alternative_plur),
                            )
                        )

    else:
        for i in range(len(tokens)):
            for word, alternative_sing, alternative_plur, subcategory in zip(
                df["Lemma"],
                df["Sg_all_clean"],
                df["Pl_all_clean"],
                df["Primary_subcategory"],
            ):
                if tokens[i].lemma_ == word:
                    if tokens[i].morph.get("Number")[0] == "Sing":
                        list_tokens.append(
                            ResultOut.factory(
                                config,
                                lang,
                                tokens[i].text,
                                full_text,
                                category,
                                subcategory,
                                tokens[i].idx,
                                None,
                                ast.literal_eval(alternative_sing),
                            )
                        )
                        if tokens[i - 1].text == "der":
                            list_tokens.append(
                                ResultOut.factory(
                                    config,
                                    lang,
                                    tokens[i - 1].text,
                                    full_text,
                                    category,
                                    subcategory,
                                    tokens[i - 1].idx,
                                    None,
                                    ["der~die"],
                                )
                            )
                        elif tokens[i - 1].text == "einer":
                            list_tokens.append(
                                ResultOut.factory(
                                    config,
                                    lang,
                                    tokens[i - 1].text,
                                    full_text,
                                    category,
                                    subcategory,
                                    tokens[i - 1].idx,
                                    None,
                                    ["einer~eine"],
                                )
                            )
                    elif tokens[i].morph.get("Number")[0] == "Plur":
                        list_tokens.append(
                            ResultOut.factory(
                                config,
                                lang,
                                tokens[i].text,
                                full_text,
                                category,
                                subcategory,
                                tokens[i].idx,
                                None,
                                ast.literal_eval(alternative_plur),
                            )
                        )

    return list_tokens


# Exaggerating words and sentences analisys function, shows alternatives if avalible


def ExaggeratingWordsSentences(
    config: Config, lang, full_text, tokens, df, df_sentences
):
    category = "style"
    subcategory = "exaggerating"
    list_tokens = []
    # Phrase matcher part to handle False positives with two words and special simbols
    matcher = PhraseMatcher(model[lang.locale].vocab)

    # Only run model.make_doc to speed things up
    patterns = [model[lang.locale].make_doc(text) for text in terms_exaggerating]
    matcher.add("TerminologyList", patterns)

    for token in tokens:
        for word, alternative in zip(df["Lemma"], df["Alternatives"]):
            if GetNonNounLowerCased(token) == word:
                list_tokens.append(
                    ResultOut.factory(
                        config,
                        lang,
                        token.text,
                        full_text,
                        category,
                        subcategory,
                        token.idx,
                        None,
                        ast.literal_eval(alternative),
                    )
                )

    matches = matcher(tokens)
    for match_id, start, end in matches:
        for sentence, alternative in zip(
            df_sentences["Lemma"], df_sentences["Alternatives"]
        ):
            span = tokens[start:end]
            if span.text == sentence:
                list_tokens.append(
                    ResultOut.factory(
                        config,
                        lang,
                        span.text,
                        full_text,
                        category,
                        subcategory,
                        span.start_char,
                        span.end_char,
                        ast.literal_eval(alternative),
                    )
                )

    return list_tokens


# Unified function for Emty words false positives and rules


def StyleWordAnalysis(config: Config, lang, full_text, tokens, terms, df, df_sentence):
    # category = df_style_sentences(["subcategory"])
    category = "style"
    # subcategory = ""
    list_tokens = []
    list_false_positives = []
    # Phrase matcher part to handle False positives with two words and special simbols
    matcher = PhraseMatcher(model[lang.locale].vocab)

    # Only run model.make_doc to speed things up
    patterns = [model[lang.locale].make_doc(text) for text in terms]
    matcher.add("TerminologyList", patterns)

    for i in range(len(tokens))[1:-1]:
        # check if the user query have false positives
        if IsItFalsePositive(tokens[i].lemma_, false_positive_style):
            # recognise if there is Name of organisation or geographical name in the query
            if len(tokens.ents) > 0:
                # this output will be deleted in production
                list_false_positives.append(
                    {"false positives": tokens[i].text, "category": category}
                )
            else:
                for word, alternative, subcategory in zip(
                    df["Lemma"], df["Alt_split"], df["Primary_subcategory"]
                ):
                    if tokens[i].lemma_ == word:
                        list_tokens.append(
                            ResultOut.factory(
                                config,
                                lang,
                                tokens[i].text,
                                full_text,
                                category,
                                subcategory,
                                tokens[i].idx,
                                tokens[i].idx + len(tokens[i].text),
                                ast.literal_eval(alternative),
                            )
                        )

        else:
            for word, alternative, subcategory in zip(
                df["Lemma"], df["Alt_split"], df["Primary_subcategory"]
            ):
                if tokens[i].lemma_ == word:
                    list_tokens.append(
                        ResultOut.factory(
                            config,
                            lang,
                            tokens[i].text,
                            full_text,
                            category,
                            subcategory,
                            tokens[i].idx,
                            tokens[i].idx + len(tokens[i].text),
                            ast.literal_eval(alternative),
                        )
                    )

    matches = matcher(tokens)
    for match_id, start, end in matches:
        for sentence, alternative, subcategory in zip(
            df_sentence["Lemma"],
            df_sentence["Alt_split"],
            df_sentence["Primary_subcategory"],
        ):
            span = tokens[start:end]
            if span.text == sentence:
                list_tokens.append(
                    ResultOut.factory(
                        config,
                        lang,
                        span.text,
                        full_text,
                        category,
                        subcategory,
                        span.start_char,
                        span.end_char,
                        ast.literal_eval(alternative),
                    )
                )

    return list_tokens


# Unified function for rules and sentence false positives


def RulesBasedWordsPhraseMatcher(
    config: Config, lang, full_text, tokens, terms, df, category, subcategory
):

    list_tokens = []
    # Phrase matcher part to handle False positives with two words and special simbols
    matcher = PhraseMatcher(model[lang.locale].vocab)

    # Only run model.make_doc to speed things up
    patterns = [model[lang.locale].make_doc(text) for text in terms]
    matcher.add("TerminologyList", patterns)

    for token in tokens:
        for word in list(df["Lemma"]):
            if GetNonNounLowerCased(token) == word:
                list_tokens.append(
                    ResultOut.factory(
                        config,
                        lang,
                        token.text,
                        full_text,
                        category,
                        subcategory,
                        token.idx,
                        None,
                        [],
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
                full_text,
                category,
                subcategory,
                span.start_char,
                span.end_char,
                [],
            )
        )

    return list_tokens


# Unified function for rules


def RulesBased(config: Config, lang, full_text, tokens, df, category, subcategory):
    list_tokens = []
    for token in tokens:
        for word in list(df["Lemma"]):
            if GetNonNounLowerCased(token) == word:
                list_tokens.append(
                    ResultOut.factory(
                        config,
                        lang,
                        token.text,
                        full_text,
                        category,
                        subcategory,
                        token.idx,
                        None,
                        [],
                    )
                )

    return list_tokens


# Deutshe Bahn realated rule. Function to catch masculine words in sentences like
# Deutshe Bahn als.. Deutshe Bahn ist..


def MisgenderingInstitutions(config: Config, lang, full_text, tokens):
    category = "style"
    subcategory = "misgendering_institutions"
    db_match_list = []
    matcher_db = Matcher(model[lang.locale].vocab)
    # Add match ID "DB" with no callback and one pattern
    pattern_db = [
        {"TEXT": "Deutsche"},
        {"TEXT": "Bahn"},
        {"LEMMA": "sein", "OP": "*"},
        {"POS": "ADV", "OP": "*"},
        {"TEXT": "als", "OP": "*"},
        {"TAG": "ART", "OP": "*"},
        {"POS": "ADJ", "OP": "*"},
        {"POS": "NOUN", "MORPH": {"IS_SUPERSET": ["Gender=Masc"]}},
    ]
    # use greedy = "LONGEST" to find all matches in the text related to pattern
    matcher_db.add("DB", [pattern_db], greedy="LONGEST")
    matches_db = matcher_db(tokens)

    for match_id, start, end in matches_db:
        span = tokens[start:end]  # The matched span
        db_match_list.append(
            ResultOut.factory(
                config,
                lang,
                span.text,
                full_text,
                category,
                subcategory,
                span.start_char,
                span.end_char,
                [span.text + "in"],
            )
        )
    return db_match_list


# function to catch ending in gendered denom
# Rules based english function


def RulesBasedEN(config: Config, lang, full_text, tokens, df, category, subcategory):
    list_tokens = []

    for token in tokens:
        for word in list(df["Lemma"]):
            if token.lemma_ == word:
                list_tokens.append(
                    ResultOut.factory(
                        config,
                        lang,
                        token.text,
                        full_text,
                        category,
                        subcategory,
                        token.idx,
                        None,
                        [],
                    )
                )

    return list_tokens


# English function
def RulesBasedWordsPhraseMatcherEN(
    config: Config, lang, full_text, tokens, df, df_sentence, category
):
    list_tokens = []
    # Phrase matcher part to handle False positives with two words and special simbols
    matcher = PhraseMatcher(model[lang.locale].vocab)

    # Only run model.make_doc to speed things up
    patterns = [
        model[lang.locale].make_doc(text) for text in list(df_sentence["Lemma"])
    ]
    matcher.add("TerminologyList", patterns)

    for token in tokens:
        for word, alternative, subcategory in zip(
            df["Lemma"], df["Alt_split"], df["Primary_subcategory"]
        ):
            if token.lemma_ == word:
                list_tokens.append(
                    ResultOut.factory(
                        config,
                        lang,
                        token.text,
                        full_text,
                        category,
                        subcategory,
                        token.idx,
                        token.idx + len(token.text),
                        ast.literal_eval(alternative),
                    )
                )

    matches = matcher(tokens)
    for match_id, start, end in matches:
        for sentence, alternative, subcategory in zip(
            df_sentence["Lemma"],
            df_sentence["Alt_split"],
            df_sentence["Primary_subcategory"],
        ):
            span = tokens[start:end]
            if span.text == sentence:
                list_tokens.append(
                    ResultOut.factory(
                        config,
                        lang,
                        span.text,
                        full_text,
                        category,
                        subcategory,
                        span.start_char,
                        span.end_char,
                        ast.literal_eval(alternative),
                    )
                )

    return list_tokens


# english function, no alternatives


def RulesBasedWordsPhraseMatcherNoAltEN(
    config: Config, lang, full_text, tokens, df, df_sentence, category
):
    list_tokens = []
    # Phrase matcher part to handle False positives with two words and special simbols
    matcher = PhraseMatcher(model[lang.locale].vocab)

    # Only run model.make_doc to speed things up
    patterns = [
        model[lang.locale].make_doc(text) for text in list(df_sentence["Lemma"])
    ]
    matcher.add("TerminologyList", patterns)

    for token in tokens:
        for word, subcategory in zip(df["Lemma"], df["Primary_subcategory"]):
            if token.lemma_ == word:
                list_tokens.append(
                    ResultOut.factory(
                        config,
                        lang,
                        token.text,
                        full_text,
                        category,
                        subcategory,
                        token.idx,
                        token.idx + len(token.text),
                        [],
                    )
                )

    matches = matcher(tokens)
    for match_id, start, end in matches:
        for sentence, subcategory in zip(
            df_sentence["Lemma"], df_sentence["Primary_subcategory"]
        ):
            span = tokens[start:end]
            if span.text == sentence:
                list_tokens.append(
                    ResultOut.factory(
                        config,
                        lang,
                        span.text,
                        full_text,
                        category,
                        subcategory,
                        span.start_char,
                        span.end_char,
                        [],
                    )
                )

    return list_tokens


# want to server to run app.py in the folder app as main app, port=8000 is defaut port for the fast api
# reload=True is debag mode in Flask is on, to set =False, when deploy the app to the production
# might be added host="0.0.0.0"
if __name__ == "__main__":
    # If this is being ran directly as a script, run an internal uvicorn server
    # to service API requests
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level=settings.logging_config_level)
