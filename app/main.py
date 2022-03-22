import ast
import re
import uvicorn
import json
import secrets
from aiohttp import ClientSession, TCPConnector, ClientError
import copy

from fastapi import (
    FastAPI,
    Request,
    Response,
    HTTPException,
    Depends,
    status,
    Header,
)

from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.security import (
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPBearer,
)
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import RedirectResponse

from typing import Optional, Union

from sentry_sdk.integrations.asgi import SentryAsgiMiddleware

from spacy.tokens import Doc
from spacy.matcher import PhraseMatcher, Matcher

from app.models import (
    Config,
    GenderedRolesFormatType,
    GermanGenderEnding,
    LangType,
    SingularThey,
    Language,
    RequestIn,
    Result,
    ResultOut,
    ResultsOut,
    ConfRequest,
)

from fastapi_microsoft_identity import validate_scope, AuthError


from app.lang_detection import LangDetection
from app.categories import categories
from app.settings import get_settings
from app.logger import set_up_logger
from app.redis_setup import set_up_redis
from app.languagetool import get_languagetool_url
from app.azure_ad_b2c import initialize_aadb2c
from app.model import model
from app.rules import *

from collections import namedtuple, defaultdict

from collections import namedtuple
from app.sentry import set_up_sentry_sdk

version = "1.22.12"

settings = get_settings()
logging = set_up_logger(settings)
sentry_sdk = set_up_sentry_sdk(version, settings)
languagetool_url = get_languagetool_url(settings)
redis = set_up_redis(settings)
lang_detection = LangDetection()
initialize_aadb2c(settings)

logging.debug("app started with settings: %s", settings)


app = FastAPI(
    title="Witty NLP API",
    version=version,
    terms_of_service=settings.terms_of_service,
    contact=settings.contact,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# Uncaught exceptions (like `raise Exception`) should propagate correctly
# to Sentry's error handler
# Middleware will also enable Sentry performance monitoring to work as expected
try:
    app.add_middleware(SentryAsgiMiddleware)
except Exception:
    # pass silently if the Sentry integration failed
    pass


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
    lang = Language(language)
    categories_with_labels[language] = copy.deepcopy(categories)
    for category in categories_with_labels[language]:
        parent_category = categories[category]["category"]

        del categories_with_labels[language][category]["importance"]

        categories_with_labels[language][category]["label"] = lang._(
            "rules." + category + "_label"
        )

# corporate false positive DB
def get_false_positive_from_redis(userId: str):
    keys = redis.keys("*")
    for key in keys:
        user_list = json.loads(redis.get(key))["users"]
        if userId in user_list:
            return json.loads(redis.get(key))["false_positive"]

        return []


FalsePositive = namedtuple("FalsePositive", "gender agentic")
# TODO: userId will be taken from the authentication token
def get_false_positive(gender_false_positive, false_positive_agentic_const, userId=""):
    corporate_false_positive = []
    if userId:
        corporate_false_positive = get_false_positive_from_redis(userId)
    fp = FalsePositive(
        gender_false_positive + corporate_false_positive,
        false_positive_agentic_const + corporate_false_positive,
    )
    return fp


false_positive = get_false_positive(
    rules["de-DE"]["gender_false_positive"],
    rules["de-DE"]["false_positive_agentic_const"],
)


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


# debugging routes
@app.post(
    "/exception",
    include_in_schema=not settings.is_prod,
)
async def exception(
    request: Request,
    user_request_in: RequestIn,
    username: str = Depends(get_current_username),
):
    configure_sentry(request, user_request_in)

    raise HTTPException(status_code=500, detail=user_request_in.text)


@app.get("/lt", include_in_schema=not settings.is_prod)
def get_lt(username: str = Depends(get_current_username)):
    return languagetool_url


@app.get("/docs", include_in_schema=False)
def get_swagger_documentation(
    username: str = Depends(get_current_username),
    include_in_schema=not settings.is_prod,
):
    return get_swagger_ui_html(openapi_url="/openapi.json", title="docs")


@app.get("/openapi.json", include_in_schema=False)
def openapi(username: str = Depends(get_current_username)):
    return get_openapi(title=app.title, version=app.version, routes=app.routes)


# public routes
@app.get("/", include_in_schema=False)
def root():
    url = "https://www.witty.works/form"
    status_code = 301

    if settings.platform_environment == "local" and settings.testing == False:
        url = "/docs"
        status_code = 302

    return RedirectResponse(url=url, status_code=status_code)


@app.get(
    "/save_openapi_json",
    include_in_schema=not settings.is_prod,
)
def save_openapi_json(username: str = Depends(get_current_username)):
    openapi_data = app.openapi()
    for path in openapi_data["paths"].copy():
        if not "v1.1" in path:
            del openapi_data["paths"][path]

    with open("openapi.json", "w") as file:
        json.dump(openapi_data, file, indent=4, sort_keys=True)


@app.get(
    "/german_gender_ending",
    include_in_schema=not settings.is_prod,
)
def german_gender_ending(
    alternative: str,
    german_gender_ending: GermanGenderEnding = None,
    username: str = Depends(get_current_username),
):
    alternative_variations = set()

    german_gender_endings = Config._gendereddenom_ending.keys()
    if german_gender_ending != None:
        german_gender_endings = [german_gender_ending]

    for german_gender_ending in german_gender_endings:
        alternative_variations.update(
            ResultOut.getAlternativeVariations(
                GenderedRolesFormatType.BOTH, german_gender_ending, alternative
            )
        )

    return alternative_variations


@app.post(
    "/auth",
    dependencies=[Depends(HTTPBearer())],
)
def auth(request: Request):
    return validate_scope(settings.aadb2c_expected_scope, request)


@app.get("/form", include_in_schema=False)
def form():
    return root()


@app.get("/categories")
def get_categories(lang: LangType = "de"):
    return categories_with_labels[lang]


@app.post(
    "/check",
    response_model=Union[ResultsOut, Result],
)
async def check_v1_0(
    request: Request,
    response: Response,
    user_request_in: RequestIn,
):
    return await check(1.0, request, response, user_request_in)


@app.post(
    "/v1.1/check",
    response_model=Union[ResultsOut, Result],
    response_model_exclude_none=True,
    dependencies=[Depends(HTTPBearer(auto_error=False))],
)
async def check_v1_1(
    request: Request,
    response: Response,
    user_request_in: RequestIn,
):
    return await check(1.1, request, response, user_request_in)


# data exchange routes
@app.post("/store_rules")
async def store_redis(
    corporate_rules: ConfRequest, username: str = Depends(get_current_username)
):
    try:
        key = str(corporate_rules.organization)
        rules = redis.get(key)
        if rules:
            rules = json.loads(rules)

        organization_object = {
            "users": corporate_rules.users,
            "config": {
                "forced": dict(corporate_rules.forced),
                "suggestion": dict(corporate_rules.suggestion),
            },
            "false_positive": corporate_rules.false_positive,
        }

        # Set a value
        redis.set(key, json.dumps(organization_object))
        for user in corporate_rules.users:
            redis.set(str(user), key)

        if rules:
            for user in rules["users"]:
                if user not in corporate_rules.users:
                    redis.delete(str(user))

    except Exception as e:
        return e
    return organization_object


@app.get("/get_user_rules")
async def get_redis(user: str, username: str = Depends(get_current_username)):
    try:
        key = redis.get(user)
        if key:
            rules = json.loads(redis.get(key))
            if user in rules["users"]:
                del rules["users"]
                return rules
            else:
                return []
    except Exception as e:
        return e


# Functions
def is_number_list_empty(number, token, full_text):
    if not number:
        start = max(token.idx - 100, 0)
        end = min(token.idx + 100, len(full_text) - 1)
        context = full_text[start:end]

        logging.error(
            "List of token morph number: %s for token/word: %s\n%s",
            number,
            token.text,
            context,
        )

        return True

    return False


def configure_sentry(request: Request, user_request_in: RequestIn):
    if sentry_sdk:
        sentry_sdk.transaction = request.scope["path"][1:]
        sentry_sdk.set_user({"id": str(user_request_in.id)})

        data = user_request_in.dict(exclude={"text"})
        data["text"] = {
            "length": len(user_request_in.text),
        }
        data["origin"] = request.headers.get("origin")

        sentry_sdk.set_context("request", data)


async def set_rules(user_request_in: RequestIn, email=str):
    general_config = Config()
    corporate_rules = await get_redis(email)
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
                # organization not set a value or set on default, user can set/change it
                else:
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


async def check(
    version: float,
    request: Request,
    response: Response,
    user_request_in: RequestIn,
):
    if version != 1.0 and version != 1.1:
        response.status_code = status.HTTP_400_BAD_REQUEST
        return Result.factory("Version not supported: " + str(version))

    configure_sentry(request, user_request_in)

    if settings.read_rules_from_redis:
        try:
            claims = validate_scope(settings.aadb2c_expected_scope, request)
            try:
                await set_rules(user_request_in, claims["emails"][0])
            except KeyError:
                pass
        except AuthError as e:
            logging.debug("token autrh error: %s", e.error_msg)

    text = user_request_in.text
    limit_reached = len(text) > settings.text_max_length
    if limit_reached:
        text = text[0 : settings.text_max_length]
        text = text.rsplit(" ", 1)[0]

    locale = lang_detection.get_locale(
        text,
        user_request_in.lang,
        user_request_in.config.preferred_languages,
        user_request_in.config.preferred_variants,
    )

    if locale == None:
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        return Result.factory("Language could not be determined")

    lang = Language(locale)

    list_results = await language_rules(version, user_request_in.config, lang, text)

    return ResultsOut.factory(list_results, lang.lang, limit_reached)


def get_alternatives(match):
    alternatives = []
    if "replacements" in match:
        for replacement in match["replacements"]:
            value = replacement["value"]
            value = value if value != "" else "-"
            alternatives.append(value)

    return alternatives


def languagetool_matches(
    version: float, config: Config, lang: Language, category: str, text: str, result
):
    list_results = []
    ignore = ["@", "#"]

    for match in result["matches"]:
        offset = int(match["offset"])
        end = offset + int(match["length"])
        highlight_text = text[offset:end]

        # ignore text that starts with @ or #
        if highlight_text[0:1] in ignore or (
            offset > 0 and text[offset - 1 : offset] in ignore
        ):
            continue

        alternatives = get_alternatives(match)

        label = match["shortMessage"]
        if label == "":
            try:
                label = match["rule"]["category"]["name"]
            except KeyError:
                pass

        try:
            subcategory = match["rule"]["category"]["id"].lower()
        except KeyError:
            subcategory = category

        explanation = match["message"]

        list_results.append(
            ResultOut.factory(
                version,
                config,
                lang,
                highlight_text,
                text,
                category,
                subcategory,
                offset,
                end,
                alternatives,
                label,
                explanation,
            )
        )

    return list_results


async def languagetool_rules(version: float, config: Config, lang: Language, text: str):
    list_results = []

    async with ClientSession(
        connector=TCPConnector(verify_ssl=settings.languagetool_verify_ssl)
    ) as session:
        payload = {
            "text": text,
            "language": lang.locale,
            "motherTongue": config.primary_language,
        }

        spelling_categories = list(
            set(config.disabled_categories) - set(categories.keys())
        )

        if len(spelling_categories) > 0:
            spelling_categories = [
                spelling_category.upper() for spelling_category in spelling_categories
            ]
            payload["disabledCategories"] = spelling_categories

        async with session.post(languagetool_url + "/check", data=payload) as r:
            try:
                assert r.status == 200
                result = await r.json()

                list_results = languagetool_matches(
                    version, config, lang, "orthography", text, result
                )
            except ClientError as err:
                result = "Problem communicating with LanguageTool"
                if r.status >= 500:
                    try:
                        response = await r.text()
                        result += ": " + response
                    except ClientError as err:
                        result += ": " + str(err)
                else:
                    result += ": " + str(err)

                logging.error(result)

    return list_results


async def language_rules(version: float, config: Config, lang: Language, text: str):
    # apply SpaCy pre-built model
    tokens = model[lang.lang](text.rstrip().replace("\n", " "))

    # functions for German rules
    if lang.lang == "de":
        list_results = german_rules(version, config, lang, tokens, text)

    # function for English rules
    elif lang.lang == "en":
        list_results = english_rules(version, config, lang, tokens, text)

    else:
        list_results = []

    if is_sub_category_enabled(config, "orthography"):
        try:
            languagetool_results = await languagetool_rules(version, config, lang, text)
            list_results = languagetool_results + list_results
        except Exception:
            pass

    return list_results


# Function for all German rules


def is_not_noun(pos):
    return pos != "NOUN" and pos != "PROPN" and pos != "PRON"


def get_non_noun_lower_cased(token):
    token_word = token.lemma_
    if is_not_noun(token.pos_):
        token_word = token_word.lower()

    return token_word


def check_category_importance(config: Config, subcategory: str):
    return (
        config.maximum_importance == None
        or categories[subcategory]["importance"] == None
        or config.maximum_importance >= categories[subcategory]["importance"]
    )


# function to convern word_type to SpaCy part-of-the-speech labels
def type_transform(lemma_type):
    if lemma_type == "s":
        return "NOUN"
    if lemma_type == "v":
        return "VERB"
    if lemma_type == "a":
        return "ADJ"
    if lemma_type == "adv":
        return "ADV"


def is_sub_category_enabled(config: Config, subcategory: str):
    if categories[subcategory]["category"] in config.disabled_categories:
        return False

    return check_category_importance(config, subcategory)


def german_rules(version: float, config: Config, lang: Language, tokens, text: str):
    list_full = []

    list_full += abbreviation_match(
        version,
        config,
        lang,
        text,
        tokens,
        rules["de-DE"]["df_abbreviation"],
        abbreviation,
    )

    if is_sub_category_enabled(config, "openly_discriminating"):
        list_full += rules_based_words_phrase_matcher_de(
            version,
            config,
            lang,
            text,
            tokens,
            open_disc_words_alternatives,
            open_disc_sentences_alternatives,
            rules["de-DE"]["df_open_dis_sentence"],
            "openly_discriminating",
        )

    if is_sub_category_enabled(config, "gendered"):
        list_full += rules_based_words_phrase_matcher_de(
            version,
            config,
            lang,
            text,
            tokens,
            gender_words_alternatives_no_noun,
            gender_sentences_alternatives,
            rules["de-DE"]["df_gendered_sentences"],
            "gendered",
        ) + gendered_denom_analysis_de(
            version,
            config,
            lang,
            text,
            tokens,
            gender_words_alternatives,
        )

    if is_sub_category_enabled(config, "misgendering_institutions"):
        list_full += misgendering_institutions_de(version, config, lang, text, tokens)

    if is_sub_category_enabled(config, "gendered_denominations_ending"):
        list_full += gendered_denom_end(version, config, lang, text)

    if is_sub_category_enabled(config, "unconscious_bias"):
        list_full += ub_words_phrase_matcher_de(
            version,
            config,
            lang,
            text,
            tokens,
            bias_words_alternatives_no_plur,
            bias_sentences_alternatives,
            rules["de-DE"]["df_ub_sentences"],
            "unconscious_bias",
        ) + agentic_language_analysis_de(
            version,
            config,
            lang,
            text,
            tokens,
            bias_words_alternatives_noun,
            "unconscious_bias",
        )

    if is_sub_category_enabled(config, "communal"):
        list_full += rules_based(
            version,
            config,
            lang,
            text,
            tokens,
            rules["de-DE"]["df_communal_words"],
            "inclusive",
            "communal",
        )

    if is_sub_category_enabled(config, "d_and_i"):
        list_full += rules_based_words_phrase_matcher(
            version,
            config,
            lang,
            text,
            tokens,
            rules["de-DE"]["terms_d_and_i_words"],
            rules["de-DE"]["df_d_and_i_words"],
            "inclusive",
            "d_and_i",
        )

    if is_sub_category_enabled(config, "style"):
        list_full += style_word_analysis_de(
            version,
            config,
            lang,
            text,
            tokens,
            rules["de-DE"]["terms_style"],
            style_words_alternatives,
            style_sentences_alternatives,
        )

    return list_full


# Function for all English rules
def english_rules(version: float, config: Config, lang: Language, tokens, text: str):
    list_full = []

    words_alternatives_en = defaultdict(list)
    inclusive_words_alternatives_en = []
    gendered_words_alternatives_en = defaultdict(list)
    inclusive_sentences_alternatives_en = []
    sentences_alternatives_en = defaultdict(list)

    if lang.locale == "en-GB":
        words_alternatives_en["od"] = open_disc_words_alternatives_GB
        words_alternatives_en["ge"] = gender_words_alternatives_GB
        words_alternatives_en["style"] = style_words_alternatives_GB
        words_alternatives_en["bias"] = bias_words_alternatives_GB
        words_alternatives_en["homonym"] = homonyms_word_GB
        words_alternatives_en["abbr"] = abbreviation_GB

        if config.singular_they == SingularThey.ALL_PRONOUNS:
            words_alternatives_en["ge"] += bias_singular_they_alternatives_GB

        inclusive_words_alternatives_en = inclusive_words_alternatives_GB
        gendered_words_alternatives_en["gendered"] = gender_noun_words_alternatives_GB
        gendered_words_alternatives_en["bias"] = gender_bias_words_alternatives_GB
        inclusive_sentences_alternatives_en = inclusive_sentences_alternatives_GB
        sentences_alternatives_en["od"] = open_dis_sentences_GB
        sentences_alternatives_en["ge"] = gender_sentences_alternatives_GB
        sentences_alternatives_en["style"] = style_sentences_alternatives_GB
        sentences_alternatives_en["bias"] = bias_sentences_alternatives_GB
    else:
        words_alternatives_en["od"] = open_disc_words_alternatives_US
        words_alternatives_en["ge"] = gender_words_alternatives_US
        words_alternatives_en["style"] = style_words_alternatives_US
        words_alternatives_en["bias"] = bias_words_alternatives_US
        words_alternatives_en["homonym"] = homonyms_word_US
        words_alternatives_en["abbr"] = abbreviation_US

        if config.singular_they == SingularThey.ALL_PRONOUNS:
            words_alternatives_en["ge"] += bias_singular_they_alternatives_US

        inclusive_words_alternatives_en = inclusive_words_alternatives_US
        gendered_words_alternatives_en["gendered"] = gender_noun_words_alternatives_US
        gendered_words_alternatives_en["bias"] = gender_bias_words_alternatives_US
        inclusive_sentences_alternatives_en = inclusive_sentences_alternatives_US
        sentences_alternatives_en["od"] = open_dis_sentences_US
        sentences_alternatives_en["ge"] = gender_sentences_alternatives_US
        sentences_alternatives_en["style"] = style_sentences_alternatives_US
        sentences_alternatives_en["bias"] = bias_sentences_alternatives_US

    list_full += homonyms_english(
        version, config, lang, text, tokens, words_alternatives_en["homonym"]
    )
    list_full += abbreviation_match(
        version,
        config,
        lang,
        text,
        tokens,
        rules[lang.locale]["df_abbreviation"],
        words_alternatives_en["abbr"],
    )

    if is_sub_category_enabled(config, "openly_discriminating"):
        list_full += rules_based_words_phrase_matcher_en(
            version,
            config,
            lang,
            text,
            tokens,
            words_alternatives_en["od"],
            sentences_alternatives_en["od"],
            rules[lang.locale]["df_open_dis_sentence"],
            "openly_discriminating",
        )

    if is_sub_category_enabled(config, "gendered"):
        list_full += rules_based_words_phrase_matcher_en(
            version,
            config,
            lang,
            text,
            tokens,
            words_alternatives_en["ge"],
            sentences_alternatives_en["ge"],
            rules[lang.locale]["df_gendered_sentence"],
            "gendered",
        ) + gendered_en(
            version,
            config,
            lang,
            text,
            tokens,
            gendered_words_alternatives_en["gendered"],
            "gendered",
        )

    if is_sub_category_enabled(config, "inclusive"):
        list_full += rules_based_words_phrase_matcher_no_alt_en(
            version,
            config,
            lang,
            text,
            tokens,
            inclusive_words_alternatives_en,
            inclusive_sentences_alternatives_en,
            rules[lang.locale]["df_inclusive_sentence"],
            "inclusive",
        )

    if is_sub_category_enabled(config, "style"):
        list_full += rules_based_words_phrase_matcher_en(
            version,
            config,
            lang,
            text,
            tokens,
            words_alternatives_en["style"],
            sentences_alternatives_en["style"],
            rules[lang.locale]["df_style_sentence"],
            "style",
        )

    if is_sub_category_enabled(config, "unconscious_bias"):
        list_full += rules_based_words_phrase_matcher_en(
            version,
            config,
            lang,
            text,
            tokens,
            words_alternatives_en["bias"],
            sentences_alternatives_en["bias"],
            rules[lang.locale]["df_ub_sentence"],
            "unconscious_bias",
        ) + gendered_en(
            version,
            config,
            lang,
            text,
            tokens,
            gendered_words_alternatives_en["bias"],
            "unconscious_bias",
        )
    return list_full


"""Function to catch the words related to False Positive in the user query"""


def is_false_positive(word, false_positive):
    for item in false_positive:
        if word == item:
            return True

    return False


"""Function to make transform words to lowcase used for English"""


def get_lower_cased(token):
    token_word = token.lemma_

    return token_word.lower()


"""Function to catch ending in German Denom"""


def gendered_denom_end(version: float, config: Config, lang, full_text):
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
                    version,
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


def agentic_language_analysis_de(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    words_alternatives_noun,
    category,
):
    list_tokens = []
    dic_anc = {}
    list_false_positives = []
    for token in tokens:
        # check if the user query have false positives
        if is_false_positive(token.lemma_, false_positive.agentic):
            # recognise if there is Name of organisation or geographical name in the query
            for entity in tokens.ents:
                if entity.label_ == "ORG":
                    list_false_positives.append(
                        {"false positives": token.text, "category": category}
                    )

            # check if the word is adverb
            if token.pos_ == "ADV":
                list_false_positives.append(
                    {"false positives": token.text, "category": category}
                )

            # check if the word is adjective and find out how it depends on the other words to feel the contex
            elif token.pos_ == "ADJ":  # or token.tag_== "ADJD":
                dic_anc[token.lemma_] = list(token.ancestors)
                for key in dic_anc.keys():
                    if key in false_positive.agentic:
                        for item in dic_anc[key]:
                            if item.text in rules["de-DE"]["exceptions"]:
                                list_false_positives.append(
                                    {
                                        "false positives": token.text,
                                        "category": category,
                                    }
                                )
        else:
            for (
                word,
                alternative_sing,
                alternative_plur,
                subcategory,
            ) in words_alternatives_noun:
                if get_non_noun_lower_cased(token) == word:
                    token_morph_number = token.morph.get("Number")
                    if is_number_list_empty(token_morph_number, token, full_text):
                        continue

                    elif token_morph_number[0] == "Sing":
                        list_tokens.append(
                            ResultOut.factory(
                                version,
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

                    elif token_morph_number[0] == "Plur":
                        list_tokens.append(
                            ResultOut.factory(
                                version,
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


def ub_words_phrase_matcher_de(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    words_alternatives,
    sentences_alternatives,
    df_sentence,
    category,
):
    list_tokens = []
    # Phrase matcher part to handle False positives with two words and special simbols
    matcher = PhraseMatcher(model[lang.lang].vocab)

    # Only run model.make_doc to speed things up
    patterns = [model[lang.lang].make_doc(text) for text in list(df_sentence["Lemma"])]
    matcher.add("TerminologyList", patterns)

    dic_anc = {}
    list_false_positives = []
    for token in tokens:
        # check if the user query have false positives
        if is_false_positive(token.lemma_, false_positive.agentic):
            # recognise if there is Name of organisation or geographical name in the query
            for entity in tokens.ents:
                if entity.label_ == "ORG":
                    list_false_positives.append(
                        {"false positives": token.text, "category": category}
                    )

            # check if the word is adverb
            if token.pos_ == "ADV":
                list_false_positives.append(
                    {"false positives": token.text, "category": category}
                )

            # check if the word is adjective and find out how it depends on the other words to feel the contex
            elif token.pos_ == "ADJ":  # or token.tag_== "ADJD":
                dic_anc[token.lemma_] = list(token.ancestors)
                for key in dic_anc.keys():
                    if key in false_positive.agentic:
                        for item in dic_anc[key]:
                            if item.text in rules["de-DE"]["exceptions"]:
                                list_false_positives.append(
                                    {
                                        "false positives": token.text,
                                        "category": category,
                                    }
                                )
        else:
            for word, alternative, subcategory in words_alternatives:
                if get_non_noun_lower_cased(token) == word:
                    list_tokens.append(
                        ResultOut.factory(
                            version,
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
        for sentence, alternative, subcategory in sentences_alternatives:
            span = tokens[start:end]
            if span.text == sentence:
                list_tokens.append(
                    ResultOut.factory(
                        version,
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


def gendered_denom_analysis_de(
    version: float, config: Config, lang, full_text, tokens, gender_words_alternatives
):
    category = "gendered"

    list_tokens = []
    list_false_positives = []
    matcher = PhraseMatcher(model[lang.lang].vocab)

    # Only run model.make_doc to speed things up
    patterns = [model[lang.lang].make_doc(text) for text in false_positive.gender]
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

        docs = list(model[lang.lang].pipe(rest_text))
        c_doc = Doc.from_docs(docs)

        for i in range(len(c_doc)):
            for (
                word,
                alternative_sing,
                alternative_plur,
                alternative_all,
                subcategory,
            ) in gender_words_alternatives:
                if c_doc[i].lemma_ == word:
                    c_doc_morph_number = c_doc[i].morph.get("Number")
                    if is_number_list_empty(c_doc_morph_number, c_doc[i], full_text):
                        list_tokens.append(
                            ResultOut.factory(
                                version,
                                config,
                                lang,
                                c_doc[i].text,
                                full_text,
                                category,
                                subcategory,
                                c_doc[i].idx,
                                None,
                                ast.literal_eval(alternative_all),
                            )
                        )
                    else:
                        if c_doc_morph_number[0] == "Sing":
                            list_tokens.append(
                                ResultOut.factory(
                                    version,
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
                            for article, article_alternative in articles:
                                if c_doc[i - 1].text == article:
                                    list_tokens.append(
                                        ResultOut.factory(
                                            version,
                                            config,
                                            lang,
                                            c_doc[i - 1].text,
                                            full_text,
                                            category,
                                            subcategory,
                                            c_doc[i - 1].idx,
                                            None,
                                            [article_alternative],
                                        )
                                    )
                        elif c_doc_morph_number[0] == "Plur":
                            list_tokens.append(
                                ResultOut.factory(
                                    version,
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
            for (
                word,
                alternative_sing,
                alternative_plur,
                alternative_all,
                subcategory,
            ) in gender_words_alternatives:
                if tokens[i].lemma_ == word:
                    token_morph_number = tokens[i].morph.get("Number")
                    if is_number_list_empty(token_morph_number, tokens[i], full_text):
                        list_tokens.append(
                            ResultOut.factory(
                                version,
                                config,
                                lang,
                                tokens[i].text,
                                full_text,
                                category,
                                subcategory,
                                tokens[i].idx,
                                None,
                                ast.literal_eval(alternative_all),
                            )
                        )
                    else:
                        if token_morph_number[0] == "Sing":
                            list_tokens.append(
                                ResultOut.factory(
                                    version,
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
                            for article, article_alternative in articles:
                                if tokens[i - 1].text == article:
                                    list_tokens.append(
                                        ResultOut.factory(
                                            version,
                                            config,
                                            lang,
                                            tokens[i - 1].text,
                                            full_text,
                                            category,
                                            subcategory,
                                            tokens[i - 1].idx,
                                            None,
                                            [article_alternative],
                                        )
                                    )
                        elif token_morph_number[0] == "Plur":
                            list_tokens.append(
                                ResultOut.factory(
                                    version,
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


# Unified function for Emty words false positives and rules


def style_word_analysis_de(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    terms,
    style_words_alternatives,
    style_sentences_alternatives,
):
    category = "style"
    list_tokens = []
    list_false_positives = []
    # Phrase matcher part to handle False positives with two words and special simbols
    matcher = PhraseMatcher(model[lang.lang].vocab)

    # Only run model.make_doc to speed things up
    patterns = [model[lang.lang].make_doc(text) for text in terms]
    matcher.add("TerminologyList", patterns)

    for i in range(len(tokens))[1:-1]:
        # check if the user query have false positives
        if is_false_positive(tokens[i].lemma_, rules["de-DE"]["false_positive_style"]):
            # recognise if there is Name of organisation or geographical name in the query
            if len(tokens.ents) > 0:
                # this output will be deleted in production
                list_false_positives.append(
                    {"false positives": tokens[i].text, "category": category}
                )
            else:
                for word, alternative, subcategory in style_words_alternatives:
                    if tokens[i].lemma_ == word:
                        list_tokens.append(
                            ResultOut.factory(
                                version,
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
            for word, alternative, subcategory in style_words_alternatives:
                if tokens[i].lemma_ == word:
                    list_tokens.append(
                        ResultOut.factory(
                            version,
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
        for sentence, alternative, subcategory in style_sentences_alternatives:
            span = tokens[start:end]
            if span.text == sentence:
                list_tokens.append(
                    ResultOut.factory(
                        version,
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


def word_noun_de(
    version: version,
    config: Config,
    lang,
    full_text,
    tokens,
    bias_words_alternatives_noun,
    category,
):
    list_tokens = []

    for token in tokens:
        for (
            word,
            alternative_sing,
            alternative_plur,
            subcategory,
        ) in bias_words_alternatives_noun:
            if get_non_noun_lower_cased(token) == word:
                token_morph_number = token.morph.get("Number")
                if is_number_list_empty(token_morph_number, token, full_text):
                    continue
                if token_morph_number[0] == "Sing":
                    list_tokens.append(
                        ResultOut.factory(
                            version,
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

                elif token_morph_number[0] == "Plur":
                    list_tokens.append(
                        ResultOut.factory(
                            version,
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
def rules_based_words_phrase_matcher_de(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    words_alternatives,
    sentences_alternatives,
    df_sentence,
    category,
):
    list_tokens = []
    # Phrase matcher part to handle False positives with two words and special simbols
    matcher = PhraseMatcher(model[lang.lang].vocab)

    # Only run model.make_doc to speed things up
    patterns = [model[lang.lang].make_doc(text) for text in list(df_sentence["Lemma"])]
    matcher.add("TerminologyList", patterns)

    for token in tokens:
        for word, alternative, subcategory in words_alternatives:
            if get_non_noun_lower_cased(token) == word:
                list_tokens.append(
                    ResultOut.factory(
                        version,
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
        for sentence, alternative, subcategory in sentences_alternatives:
            span = tokens[start:end]
            if span.text == sentence:
                list_tokens.append(
                    ResultOut.factory(
                        version,
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


def rules_based_words_phrase_matcher(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    terms,
    df,
    category,
    subcategory,
):

    list_tokens = []
    # Phrase matcher part to handle False positives with two words and special simbols
    matcher = PhraseMatcher(model[lang.lang].vocab)

    # Only run model.make_doc to speed things up
    patterns = [model[lang.lang].make_doc(text) for text in terms]
    matcher.add("TerminologyList", patterns)

    for token in tokens:
        for word in list(df["Lemma"]):
            if get_non_noun_lower_cased(token) == word:
                list_tokens.append(
                    ResultOut.factory(
                        version,
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
                version,
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


def rules_based(
    version: float, config: Config, lang, full_text, tokens, df, category, subcategory
):
    list_tokens = []
    for token in tokens:
        for word in list(df["Lemma"]):
            if get_non_noun_lower_cased(token) == word:
                list_tokens.append(
                    ResultOut.factory(
                        version,
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


def misgendering_institutions_de(
    version: float, config: Config, lang, full_text, tokens
):
    subcategory = "misgendering_institutions"
    category = categories[subcategory]["category"]
    db_match_list = []
    matcher_db = Matcher(model[lang.lang].vocab)
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
                version,
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


# function English
def rules_based_words_phrase_matcher_en(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    words_alternatives,
    sentences_alternatives,
    df_sentence,
    category,
):
    list_tokens = []
    # Phrase matcher part to handle False positives with two words and special simbols
    matcher = PhraseMatcher(model[lang.lang].vocab)

    # Only run model.make_doc to speed things up
    patterns = [model[lang.lang].make_doc(text) for text in list(df_sentence["Lemma"])]
    matcher.add("TerminologyList", patterns)

    for token in tokens:
        for word, alternative, subcategory in words_alternatives:
            if get_lower_cased(token) == word:
                list_tokens.append(
                    ResultOut.factory(
                        version,
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
        for sentence, alternative, subcategory in sentences_alternatives:
            span = tokens[start:end]
            if span.text == sentence:
                list_tokens.append(
                    ResultOut.factory(
                        version,
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


# english function to handle homonyms
def homonyms_english(
    version: float, config: Config, lang, full_text, tokens, homonyms_words
):

    list_tokens = []
    for token in tokens:

        for word, word_type, category, subcategory, alternative in homonyms_words:
            if not is_sub_category_enabled(config, subcategory):
                continue
            if token.lemma_ == word and token.pos_ == type_transform(word_type):
                list_tokens.append(
                    ResultOut.factory(
                        version,
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
    return list_tokens


# function to find exact match for abbreviations
def abbreviation_match(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    df_abbreviation,
    abbreviation_list,
):
    list_tokens = []
    # Phrase matcher part to handle False positives with two words and special simbols
    matcher = PhraseMatcher(model[lang.lang].vocab)

    # Only run model.make_doc to speed things up
    patterns = [
        model[lang.lang].make_doc(text) for text in list(df_abbreviation["Lemma"])
    ]
    matcher.add("TerminologyList", patterns)

    matches = matcher(tokens)
    for match_id, start, end in matches:
        for abbreviation, category, subcategory, alternative in abbreviation_list:
            if not is_sub_category_enabled(config, subcategory):
                continue
            span = tokens[start:end]
            if span.text == abbreviation:
                list_tokens.append(
                    ResultOut.factory(
                        version,
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


def gendered_en(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    gendered_words_alternatives,
    category,
):
    list_tokens = []

    for token in tokens:
        for (
            word,
            alternative_sing,
            alternative_plur,
            subcategory,
        ) in gendered_words_alternatives:
            if get_lower_cased(token) == word:
                token_morph_number = token.morph.get("Number")
                if is_number_list_empty(token_morph_number, token, full_text):
                    continue
                if token_morph_number[0] == "Sing":
                    list_tokens.append(
                        ResultOut.factory(
                            version,
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

                elif token_morph_number[0] == "Plur":
                    list_tokens.append(
                        ResultOut.factory(
                            version,
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


def rules_based_words_phrase_matcher_no_alt_en(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    inclusive_words_alternatives_en,
    inclusive_sentences_alternatives_en,
    df_sentence,
    category,
):
    list_tokens = []
    # Phrase matcher part to handle False positives with two words and special simbols
    matcher = PhraseMatcher(model[lang.lang].vocab)

    # Only run model.make_doc to speed things up
    patterns = [model[lang.lang].make_doc(text) for text in list(df_sentence["Lemma"])]
    matcher.add("TerminologyList", patterns)

    for token in tokens:
        for word, subcategory in inclusive_words_alternatives_en:
            if get_lower_cased(token) == word:
                list_tokens.append(
                    ResultOut.factory(
                        version,
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
        for sentence, subcategory in inclusive_sentences_alternatives_en:
            span = tokens[start:end]
            if span.text == sentence:
                list_tokens.append(
                    ResultOut.factory(
                        version,
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
