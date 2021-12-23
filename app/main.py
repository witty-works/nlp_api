import ast
import re
from datetime import datetime
import uvicorn
import os
import json
import secrets
import aiohttp
import copy

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
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import RedirectResponse, PlainTextResponse, FileResponse

from fastapi.exception_handlers import (
    http_exception_handler,
)

from typing import Optional

import spacy
from spacy.tokens import Doc
from spacy.matcher import PhraseMatcher, Matcher
from spacy.tokenizer import Tokenizer
from spacy.lang.char_classes import (
    ALPHA,
    ALPHA_LOWER,
    ALPHA_UPPER,
    CONCAT_QUOTES,
    LIST_ELLIPSES,
    LIST_ICONS,
)
from spacy.util import compile_infix_regex


import pandas as pd

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

from app.categories import categories
from app.settings import get_settings
from app.logger import set_up_logger
from app.posthog import set_up_posthog
from app.redis import set_up_redis
from app.languagetool import get_languagetool_url

from collections import namedtuple

settings = get_settings()
logging = set_up_logger(settings)
posthog = set_up_posthog(settings)
languagetool_url = get_languagetool_url(settings)
redis = set_up_redis(settings)

logging.debug("app started with settings: %s", settings)

# Regular expression library
# convert string of list into list of the strings
# project models

version = "1.8.3"
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
        parent_category = categories[category]["category"]
        color = categories[parent_category]["color"]
        categories_with_labels[language][category]["color"] = color

        categories_with_labels[language][category]["label"] = lang._(
            "rules." + category + "_label"
        )


# Custom tokenizers
# English
def custom_tokenizer_en(nlp):
    infixes = (
        LIST_ELLIPSES
        + LIST_ICONS
        + [
            r"(?<=[0-9])[+\-\*^](?=[0-9-])",
            r"(?<=[{al}{q}])\.(?=[{au}{q}])".format(
                al=ALPHA_LOWER, au=ALPHA_UPPER, q=CONCAT_QUOTES
            ),
            r"(?<=[{a}]),(?=[{a}])".format(a=ALPHA),
            # hyphen excluded from separators
            # r"(?<=[{a}])(?:{h})(?=[{a}])".format(a=ALPHA, h=HYPHENS),
            r"(?<=[{a}0-9])[:<>=/](?=[{a}])".format(a=ALPHA),
        ]
    )

    infix_re = compile_infix_regex(infixes)

    return Tokenizer(
        nlp.vocab,
        prefix_search=nlp.tokenizer.prefix_search,
        suffix_search=nlp.tokenizer.suffix_search,
        infix_finditer=infix_re.finditer,
        token_match=nlp.tokenizer.token_match,
        rules=nlp.Defaults.tokenizer_exceptions,
    )


# German
def custom_tokenizer_de(nlp):
    _quotes = CONCAT_QUOTES.replace("'", "")
    infixes = (
        LIST_ELLIPSES
        + LIST_ICONS
        + [
            r"(?<=[{al}])\.(?=[{au}])".format(al=ALPHA_LOWER, au=ALPHA_UPPER),
            r"(?<=[{a}])[,!?](?=[{a}])".format(a=ALPHA),
            # removed : [:<>=]
            r"(?<=[{a}])[<>=](?=[{a}])".format(a=ALPHA),
            r"(?<=[{a}]),(?=[{a}])".format(a=ALPHA),
            r"(?<=[0-9{a}])\/(?=[0-9{a}])".format(a=ALPHA),
            r"(?<=[{a}])([{q}\)\]\(\[])(?=[{a}])".format(a=ALPHA, q=_quotes),
            r"(?<=[{a}])--(?=[{a}])".format(a=ALPHA),
            r"(?<=[0-9])-(?=[0-9])",
        ]
    )

    infix_re = compile_infix_regex(infixes)

    return Tokenizer(
        nlp.vocab,
        prefix_search=nlp.tokenizer.prefix_search,
        suffix_search=nlp.tokenizer.suffix_search,
        infix_finditer=infix_re.finditer,
        token_match=nlp.tokenizer.token_match,
        rules=nlp.Defaults.tokenizer_exceptions,
    )


# Model data
model = {"en": spacy.load("en_core_web_sm"), "de": spacy.load("de_core_news_sm")}

# custom tokenizer for English
model["en"].tokenizer = custom_tokenizer_en(model["en"])

# custom tokenizer for German
model["de"].tokenizer = custom_tokenizer_de(model["de"])

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
df_gender_ct = pd.read_csv("training_data/gendered_noun_DE.csv")
# load Gender denom_de false_positives
genderdenom_false_positives = pd.read_csv("training_data/titles_false_positives_DE.csv")

# load style words_de
df_style_word = pd.read_csv("training_data/style_words_DE.csv")
df_style_sentences = pd.read_csv("training_data/style_sentences_DE.csv")
# list of "hollow word" sentences
terms_style = list(df_style_sentences["Lemma"])

# load openly discriminating words de
df_open_dis_word_de = pd.read_csv("training_data/open_dis_words_DE.csv")
df_open_dis_sentence_de = pd.read_csv("training_data/open_dis_sentences_DE.csv")

# load unconscious_bias word (nouns, not nouns) and sentences de
df_ub_noun_word_de = pd.read_csv("training_data/ub_noun_words_DE.csv")
df_ub_no_noun_word_de = pd.read_csv("training_data/ub_no_noun_words_DE.csv")
df_ub_sentences_de = pd.read_csv("training_data/ub_sentences_DE.csv")

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

# load gendered language
df_gendered_no_noun_word_en = pd.read_csv("training_data/gendered_no_noun_words_EN.csv")
df_gendered_sentence_en = pd.read_csv("training_data/gendered_sentences_EN.csv")
df_gendered_noun_word_en = pd.read_csv("training_data/gendered_noun_words_EN.csv")

# dictionaries to handle false positives
false_positive_agentic_const = [
    "selbst",
    "flexible",
    "Probleme",
    "unabhängig",
    "Entwickler",
]
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

# corporate false positive DB
def get_false_positive_from_redis(userId: str):
    keys = redis.keys("*")
    for key in keys:
        user_list = json.loads(redis.get(key))["users"]
        if userId in user_list:
            return json.loads(redis.get(key))["false_positive"]
        else:
            return []


FalsePositive = namedtuple("FalsePositive", "gender agentic")
# TODO: userId will be taken from the authentication token
def get_false_positive(gender_false_positive, false_positive_agentic_const, userId=""):
    corporate_false_positive = []
    if userId:
        corporate_false_positive = get_false_positive_from_redis(userId)
    # FalsePositive = namedtuple("FalsePositive", "gender agentic")
    fp = FalsePositive(
        gender_false_positive + corporate_false_positive,
        false_positive_agentic_const + corporate_false_positive,
    )
    return fp


# terms_false_positive = gender_false_positive + corporate_false_positive
# false_positive_agentic += corporate_false_positive
false_positive = get_false_positive(gender_false_positive, false_positive_agentic_const)


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
        organization_object = {
            "users": corporate_rules.users,
            "config": {
                "forced": dict(corporate_rules.forced),
                "suggestion": dict(corporate_rules.suggestion),
            },
            "false_positive": corporate_rules.false_positive,
        }

        # Set a value
        redis.set(str(corporate_rules.organization), json.dumps(organization_object))
    except Exception as e:
        return e
    return organization_object


@app.get("/organizationRules")
async def get_redis(user: str):
    try:
        keys = redis.keys("*")
        for key in keys:
            user_list = json.loads(redis.get(key))["users"]
            if user in user_list:
                return json.loads(redis.get(key))
            # test
            else:
                return []
    except Exception as e:
        return e


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
        organization_config = {**default_filtered, **forced_filtered}

        for config_value in vars(general_config):
            # user set a value (change, if user not give a key)
            if user_rules[config_value] is not None:

                # organization set a value and user can't change it
                if (
                    config_value in organization_config
                    and config_value in forced_filtered
                ):
                    # overwrite user value
                    setattr(
                        user_request_in.config,
                        config_value,
                        forced_config[config_value],
                    )
                # organization set a value on default, user can change it
                elif (
                    config_value in organization_config
                    and config_value in default_filtered
                ):
                    # set user value
                    setattr(
                        user_request_in.config, config_value, user_rules[config_value]
                    )
                else:
                    # organization does not set a value, user can set a value
                    setattr(
                        user_request_in.config, config_value, user_rules[config_value]
                    )
            else:
                # user does not set a value, but organization did
                if config_value in organization_config:
                    setattr(
                        user_request_in.config,
                        config_value,
                        organization_config[config_value],
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
    data["origin"] = request.headers.get("origin")

    return data


def clean_response_data(store_context, response: ResultsOut):
    if store_context:
        results_hidden_fields = {"label", "reason", "solution"}
    else:
        results_hidden_fields = {"label", "reason", "solution", "context"}

    data = response.dict(exclude={"results": {"__all__": results_hidden_fields}})

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
            "response": clean_response_data(
                user_request_in.config.store_context, response
            ),
        }

    data["$useragent"] = request.headers.get("user-agent")

    return data


def write_user_training_data(
    request: Request, user_request_in: RequestIn, response: ResultsOut = None
):
    if user_request_in.id is None or not settings.training_data_enabled:
        return

    data = collect_user_training_data(request, user_request_in, response)

    if user_request_in.id in settings.posthog_ids:
        posthog.identify(user_request_in.id)

        # TODO read user/organization group from redis data
        groups = {"user": "dashboard:0", "organization": "dashboard:0"}
        posthog.capture(user_request_in.id, user_request_in.type, data, groups=groups)

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


def IsSubCategoryEnabled(subcategory, disabled_categories):
    return categories[subcategory]["category"] not in disabled_categories


def GermanRules(lang, tokens, user_request_in: RequestIn):
    list_full = []

    disabled_categories = user_request_in.config.disabled_categories

    if IsSubCategoryEnabled("openly_discriminating", disabled_categories):
        list_full += RulesBasedWordsPhraseMatcherDE(
            user_request_in.config,
            lang,
            user_request_in.text,
            tokens,
            df_open_dis_word_de,
            df_open_dis_sentence_de,
            "openly_discriminating",
        )

    if IsSubCategoryEnabled("gendered", disabled_categories):
        list_full += GenderedDenomAnalysis(
            user_request_in.config, lang, user_request_in.text, tokens, df_gender_ct
        )

    if IsSubCategoryEnabled(
        "misgendering_institutions", user_request_in.config.disabled_categories
    ):
        list_full += MisgenderingInstitutions(
            user_request_in.config, lang, user_request_in.text, tokens
        )

    if IsSubCategoryEnabled(
        "gendered_denominations_ending", user_request_in.config.disabled_categories
    ):
        list_full += GenderedDenomEnd(
            user_request_in.config, lang, user_request_in.text
        )

    if IsSubCategoryEnabled("agentic", disabled_categories):
        list_full += AgenticLanguageAnalysis(
            user_request_in.config, lang, user_request_in.text, tokens, df_agentic_ct
        )

    if IsSubCategoryEnabled("unconscious_bias", disabled_categories):
        list_full += RulesBasedWordsPhraseMatcherDE(
            user_request_in.config,
            lang,
            user_request_in.text,
            tokens,
            df_ub_no_noun_word_de,
            df_ub_sentences_de,
            "unconscious_bias",
        ) + WordNounDE(
            user_request_in.config,
            lang,
            user_request_in.text,
            tokens,
            df_ub_noun_word_de,
            "unconscious_bias",
        )

    if IsSubCategoryEnabled("communal", disabled_categories):
        list_full += RulesBased(
            user_request_in.config,
            lang,
            user_request_in.text,
            tokens,
            df_communal_words,
            "inclusive",
            "communal",
        )

    if IsSubCategoryEnabled("d_and_i", disabled_categories):
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

    if IsSubCategoryEnabled("style", disabled_categories):
        list_full += StyleWordAnalysis(
            user_request_in.config,
            lang,
            user_request_in.text,
            tokens,
            terms_style,
            df_style_word,
            df_style_sentences,
        )

    return list_full


# Function for all English rules
def EnglishRules(lang, tokens, user_request_in: RequestIn):
    list_full = []

    disabled_categories = user_request_in.config.disabled_categories

    if IsSubCategoryEnabled("openly_discriminating", disabled_categories):
        list_full += RulesBasedWordsPhraseMatcherUN(
            user_request_in.config,
            lang,
            user_request_in.text,
            tokens,
            df_open_dis_word_en,
            df_open_dis_sentence_en,
            "openly_discriminating",
        )

    if IsSubCategoryEnabled("gendered", disabled_categories):
        list_full += RulesBasedWordsPhraseMatcherUN(
            user_request_in.config,
            lang,
            user_request_in.text,
            tokens,
            df_gendered_no_noun_word_en,
            df_gendered_sentence_en,
            "gendered",
        ) + GenderedEN(
            user_request_in.config,
            lang,
            user_request_in.text,
            tokens,
            df_gendered_noun_word_en,
            "gendered",
        )

    if IsSubCategoryEnabled("agentic", disabled_categories):
        list_full += RulesBasedEN(
            user_request_in.config,
            lang,
            user_request_in.text,
            tokens,
            df_agentic_words_en,
            "unconscious_bias",
            "agentic",
        )

    if IsSubCategoryEnabled("inclusive", disabled_categories):
        list_full += RulesBasedWordsPhraseMatcherNoAltEN(
            user_request_in.config,
            lang,
            user_request_in.text,
            tokens,
            df_inclusive_word_en,
            df_inclusive_sentence_en,
            "inclusive",
        )

    if IsSubCategoryEnabled("style", disabled_categories):
        list_full += RulesBasedWordsPhraseMatcherUN(
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
    subcategory = "gendered_denominations_ending"
    category = categories[subcategory]["category"]

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
    subcategory = "agentic"
    category = categories[subcategory]["category"]
    list_tokens = []
    dic_anc = {}
    list_false_positives = []

    for token in tokens:
        # check if the user query have false positives
        if IsItFalsePositive(token.lemma_, false_positive.agentic):
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
                    if key in false_positive.agentic:
                        for item in dic_anc[key]:
                            if item.text in exceptions:
                                list_false_positives.append(
                                    {
                                        "false positives": token.text,
                                        "category": subcategory,
                                    }
                                )
        else:
            for word, alternative in zip(
                df["Lemma"], df["Alternatives_split_organization"]
            ):
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
    patterns = [model[lang.locale].make_doc(text) for text in false_positive.gender]
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
                                    ["die~der"],
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
                                    ["eine~einer"],
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
                                    ["die~der"],
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
                                    ["eine~einer"],
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
    subcategory = "exaggerating"
    category = categories[subcategory]["category"]
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


# German function to show plural and singular forms of alternatives for nouns


def WordNounDE(config: Config, lang, full_text, tokens, df, category):
    list_tokens = []

    for token in tokens:
        for word, alternative_sing, alternative_plur, subcategory in zip(
            df["Lemma"],
            df["Sg_all_split"],
            df["Pl_all_split"],
            df["Primary_subcategory"],
        ):
            if GetNonNounLowerCased(token) == word:
                if token.morph.get("Number")[0] == "Sing":
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
                            ast.literal_eval(alternative_sing),
                        )
                    )

                elif token.morph.get("Number")[0] == "Plur":
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
                            ast.literal_eval(alternative_plur),
                        )
                    )

    return list_tokens


# Unified function for rules and sentence false positives

# Unified function German
def RulesBasedWordsPhraseMatcherDE(
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
    subcategory = "misgendering_institutions"
    category = categories[subcategory]["category"]
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


# Unified function English&German
def RulesBasedWordsPhraseMatcherUN(
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


# english function to show plural and singular forms of alternatives for nouns


def GenderedEN(config: Config, lang, full_text, tokens, df, category):
    list_tokens = []

    for token in tokens:
        for word, alternative_sing, alternative_plur, subcategory in zip(
            df["Lemma"],
            df["Sg_all_split"],
            df["Pl_all_split"],
            df["Primary_subcategory"],
        ):
            if token.lemma_ == word:
                if token.morph.get("Number")[0] == "Sing":
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
                            ast.literal_eval(alternative_sing),
                        )
                    )

                elif token.morph.get("Number")[0] == "Plur":
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
                            ast.literal_eval(alternative_plur),
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
