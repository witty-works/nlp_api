import re
import uvicorn
import json
import secrets
from aiohttp import ClientSession, TCPConnector, ClientError
import copy
from app.gender import get_gender_of_word

from fastapi import (
    FastAPI,
    Request,
    Response,
    HTTPException,
    Depends,
    status,
)

from fastapi.responses import JSONResponse
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
    GermanGenderEndingType,
    LangType,
    SingularTheyType,
    Language,
    RequestIn,
    Result,
    ResultOut,
    ResultsOutOld,
    ResultsOut,
    ConfRequest,
    OrganizationConfig,
    ResultConf,
    ErrorMessage,
)

from fastapi_microsoft_identity import validate_scope, get_token_claims


from app.lang_detection import LangDetection
from app.categories import categories
from app.settings import get_settings
from app.logger import set_up_logger
from app.redis_setup import set_up_redis
from app.languagetool import get_languagetool_url
from app.azure_ad_b2c import initialize_aadb2c
from app.model import model
from app.rules import *

from collections import defaultdict

from app.sentry import set_up_sentry_sdk

version = "1.33.0"

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
):  # pragma: no cover
    configure_sentry(request, user_request_in)

    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=user_request_in.text
    )


@app.get("/lt", include_in_schema=not settings.is_prod)
def get_lt(username: str = Depends(get_current_username)):
    return languagetool_url


@app.get("/docs", include_in_schema=False)
def get_swagger_documentation(
    username: str = Depends(get_current_username),
    include_in_schema=not settings.is_prod,
):  # pragma: no cover
    return get_swagger_ui_html(openapi_url="/openapi.json", title="docs")


@app.get("/openapi.json", include_in_schema=False)
def openapi(username: str = Depends(get_current_username)):  # pragma: no cover
    return get_openapi(title=app.title, version=app.version, routes=app.routes)


# public routes
@app.get("/", include_in_schema=False)
def root():
    url = "https://www.witty.works/form"
    status_code = 301

    if not settings.is_prod and settings.testing == False:  # pragma: no cover
        url = "/docs"
        status_code = 302

    return RedirectResponse(url=url, status_code=status_code)


@app.get(
    "/save_openapi_json",
    include_in_schema=not settings.is_prod,
)
def save_openapi_json(
    username: str = Depends(get_current_username),
):  # pragma: no cover
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
    german_gender_ending: GermanGenderEndingType = None,
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
    "/auth_debug",
    include_in_schema=not settings.is_prod,
    dependencies=[Depends(HTTPBearer())],
)
async def auth(request: Request, user_request_in: RequestIn):  # pragma: no cover
    user = get_user(request)
    if not user:
        return user

    rules = await apply_rules(user_request_in, user)

    return {
        "claim": get_token_claims(request),
        "rules": rules,
        "user_request_in": user_request_in,
    }


@app.post(
    "/auth",
    response_model=Union[ResultConf, dict, None],
    response_model_exclude_none=True,
    dependencies=[Depends(HTTPBearer(auto_error=False))],
)
async def auth(request: Request, response: Response):
    user = get_user(request)
    if not user:
        return None

    organization_rules = await apply_rules(RequestIn(text=""), user)

    return get_result_conf(user, organization_rules)


@app.get("/form", include_in_schema=False)
def form():
    return root()


@app.get("/categories")
def get_categories(lang: LangType = "de"):
    return categories_with_labels[lang]


@app.post(
    "/check",
    include_in_schema=not settings.is_prod,
    response_model=Union[ResultsOutOld, Result],
)
async def check_v1_0(
    request: Request,
    response: Response,
    user_request_in: RequestIn,
):
    results, language, limit_reached, organization_config = await check(
        1.0, request, response, user_request_in
    )

    if isinstance(results, Result):
        return results

    return ResultsOutOld(
        results=results,
        language=language,
        limit_reached=limit_reached,
    )


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
    results, language, limit_reached, organization_config = await check(
        1.1, request, response, user_request_in
    )

    if isinstance(results, Result):
        return results

    return ResultsOut(
        results=results,
        language=language,
        limit_reached=limit_reached,
        organization_config=organization_config,
    )


# data exchange routes
@app.post("/store_rules")
async def store_rules(
    organization_rules: ConfRequest, username: str = Depends(get_current_username)
):
    rules = redis.get(organization_rules.id)

    # Set a value
    redis.set(organization_rules.id, organization_rules.json())
    for user in organization_rules.users:
        redis.set(str(user), organization_rules.id)

    if rules:
        rules = json.loads(rules)
        for user in rules["users"]:
            if user not in organization_rules.users:
                redis.delete(str(user))

    return organization_rules


@app.delete(
    "/delete_rules",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorMessage}},
)
async def delete_rules(
    organization_id: str,
    username: str = Depends(get_current_username),
):
    rules = redis.get(organization_id)

    if not rules:
        return JSONResponse(
            status_code=404, content={"message": "User rules not found"}
        )

    rules = json.loads(rules)
    for user in rules["users"]:
        redis.delete(str(user))

    redis.delete(organization_id)


@app.get(
    "/get_user_rules", response_model=dict, responses={404: {"model": ErrorMessage}}
)
async def get_user_rules(
    user: str,
    username: str = Depends(get_current_username),
):
    rules = await get_user_rules_from_redis(user)

    if not rules:
        return JSONResponse(
            status_code=404, content={"message": "User rules not found"}
        )

    del rules["users"]

    return rules


# Functions
async def get_user_rules_from_redis(user: str):
    key = redis.get(user)

    if key:
        rules = json.loads(redis.get(key))
        if "users" in rules and user in rules["users"]:
            return rules

    return None


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
    if sentry_sdk:  # pragma: no cover
        sentry_sdk.transaction = request.scope["path"][1:]
        sentry_sdk.set_user({"id": str(user_request_in.id)})

        data = user_request_in.dict(exclude={"text"})
        data["text"] = {
            "length": len(user_request_in.text),
        }
        data["origin"] = request.headers.get("origin")

        sentry_sdk.set_context("request", data)


def filter_config(config):
    return {k: v for (k, v) in config.items() if v != "" and v is not None and v != []}


async def apply_rules(user_request_in: RequestIn, user=Optional[str]):
    if not user:
        return {}

    organization_rules = await get_user_rules_from_redis(user)
    if not organization_rules or type(organization_rules) is not dict:
        return {}

    return merge_rules(user_request_in, organization_rules)


def merge_rules(user_request_in: RequestIn, organization_rules: list):
    categories = ["inclusive", "style", "orthography"]
    disabled_categories = user_request_in.config.disabled_categories

    for config in organization_rules["config"]:
        data = organization_rules["config"][config]
        if data is not None and data["status"] == "force":
            if config in categories:
                if data["value"]:
                    if config in disabled_categories:
                        disabled_categories.remove(config)
                elif config not in disabled_categories:
                    disabled_categories.append(config)

            else:
                user_request_in.config.__setattr__(config, data["value"])

    user_request_in.config.__setattr__("disabled_categories", disabled_categories)

    return organization_rules


def get_user(request: Request):
    if settings.testing:
        if "x-auth" in request.headers:
            return request.headers["x-auth"]
        if settings.redis_default_user:
            return settings.redis_default_user

    if "authorization" in request.headers and request.headers[
        "authorization"
    ].lower().startswith("bearer"):
        try:
            validate_scope(settings.aadb2c_expected_scope, request)
            claims = get_token_claims(request)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="access token invalid"
            )

        try:
            if claims["aud"] != settings.aadb2c_client_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="access token does not match client id",
                )

            return claims["emails"][0]
        except KeyError:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="access token does not map to email",
            )

    return None


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

    user = get_user(request)
    organization_rules = await apply_rules(user_request_in, user)
    if not organization_rules:
        user_request_in.config.store_context = True

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
        results = Result.factory("Language could not be determined")
        language = None
        organization_config = None
    else:
        lang = Language(locale)

        results = await language_rules(
            version, user_request_in.config, organization_rules, lang, text
        )

        language = lang.lang

        organization_config = get_result_conf(user, organization_rules)

    return results, language, limit_reached, organization_config


def get_result_conf(user, organization_rules: dict):
    if "config" not in organization_rules:
        if user:
            return {}

        return None

    return ResultConf(
        id=organization_rules["id"],
        name=organization_rules["name"],
        plan=organization_rules["plan"],
        config=OrganizationConfig.parse_obj(organization_rules["config"]),
    )


def get_alternatives(match):
    alternatives = []
    if "replacements" in match:
        for replacement in match["replacements"]:
            value = replacement["value"]
            value = value if value != "" else "-"
            alternatives.append(value)

    return alternatives


def has_gender_denom_ending(text, full_text, offset, config: Config):
    offset_with_text = offset + len(text)
    for ending in config._gendereddenom_ending:
        if full_text[offset_with_text : offset_with_text + len(ending)] == ending:
            return True

        # innen case
        ending = ending + "nen"
        if full_text[offset_with_text : offset_with_text + len(ending)] == ending:
            return True

    return False


def languagetool_matches(
    version: float, config: Config, lang: Language, category: str, text: str, result
):
    list_results = []
    ignore = ["@", "#"]

    gendered_denom = (
        lang.lang == "de"
        and is_sub_category_enabled(config, "gendered_denominations_ending")
        and ResultOut.genderedRolesFormatInclusive(config.gendered_roles_format)
    )

    for match in result["matches"]:
        offset = int(match["offset"])
        end = offset + int(match["length"])
        highlight_text = text[offset:end]

        # ignore text that starts with @ or #
        if highlight_text[0:1] in ignore or (
            offset > 0 and text[offset - 1 : offset] in ignore
        ):
            continue

        # ignore german gender ending as spelling mistakes
        if gendered_denom and has_gender_denom_ending(
            highlight_text, text, offset, config
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
        }

        if config.primary_language != None:
            payload["motherTongue"] = config.primary_language

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
                if r.status != 200:  # pragma: no cover
                    result = await r.text()
                    logging.error(result)

                    raise Exception(result)

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


async def language_rules(
    version: float, config: Config, organization_rules: dict, lang: Language, text: str
):
    # apply SpaCy pre-built model
    tokens = model[lang.lang](text.rstrip().replace("\n", " "))

    list_results = []
    if is_sub_category_enabled(config, "orthography"):
        try:
            list_results += await languagetool_rules(version, config, lang, text)
        except Exception as err:
            if not settings.is_prod:  # pragma: no cover
                raise err

    # functions for German rules
    if lang.lang == "de":
        list_results += german_rules(version, config, lang, tokens, text)

    # function for English rules
    elif lang.lang == "en":
        list_results += english_rules(version, config, lang, tokens, text)

    if "term_replacements" in organization_rules:
        term_replacements = {
            "Lemma": [],
            "Category": [],
            "Primary_subcategory": [],
            "Alt_split": [],
            "Explanation": [],
        }

        for term_replacement in organization_rules["term_replacements"]:
            term_replacements["Lemma"].append(term_replacement["term"])
            term_replacements["Category"].append("corporate_rules")
            term_replacements["Primary_subcategory"].append("corporate_rules")
            term_replacements["Alt_split"].append(term_replacement["alternatives"])
            term_replacements["Explanation"].append(term_replacement["explanation"])

        df_term_replacements = pd.DataFrame(data=term_replacements)
        alternatives = list(
            zip(
                df_term_replacements["Lemma"],
                df_term_replacements["Category"],
                df_term_replacements["Primary_subcategory"],
                df_term_replacements["Alt_split"],
                df_term_replacements["Explanation"],
            )
        )

        list_results += literal_match(
            version,
            config,
            lang,
            text,
            tokens,
            df_term_replacements,
            alternatives,
        )

    false_positives = []
    if "false_positives" in organization_rules:
        false_positives = organization_rules["false_positives"]

    if "term_replacements" in organization_rules:
        for rule in organization_rules["term_replacements"]:
            false_positives.append(rule["alternatives"][0])

    if false_positives != []:
        for result in list_results:
            if result.text in false_positives:
                list_results.remove(result)

    return list_results


# Function for all German rules
def get_lemma_lower_cased(token):
    token_word = token.lemma_

    return token_word.lower()


def get_lemma_non_noun_lower_cased(token):
    if token.pos_ != "NOUN" and token.pos_ != "PROPN" and token.pos_ != "PRON":
        return get_lemma_lower_cased(token)

    return token.lemma_


def check_category_importance(config: Config, subcategory: str):
    return (
        config.maximum_importance == None
        or categories[subcategory]["importance"] == None
        or config.maximum_importance >= categories[subcategory]["importance"]
    )


def is_sub_category_enabled(config: Config, subcategory: str):
    if subcategory not in categories:
        if not settings.is_prod:
            logging.error(
                "Subcategory is not defined: %s",
                subcategory,
            )

        return False

    if categories[subcategory]["category"] in config.disabled_categories:
        return False

    return check_category_importance(config, subcategory)


def german_rules(version: float, config: Config, lang: Language, tokens, text: str):
    list_full = []

    list_full += literal_match(
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
            false_positives.gender,
        )

    if is_sub_category_enabled(config, "misgendering_institutions"):
        list_full += misgendering_institutions_de(version, config, lang, text, tokens)

    if is_sub_category_enabled(
        config, "gendered_denominations_ending"
    ) and ResultOut.genderedRolesFormatInclusive(config.gendered_roles_format):
        subcategory = "gendered_denominations_ending"
        category = categories[subcategory]["category"]
        endings = config._gendereddenom_ending.copy()
        if config.german_gender_ending in endings:
            del endings[config.german_gender_ending]

        list_full += gendered_denom_end(
            version,
            config,
            lang,
            text,
            category,
            subcategory,
            endings,
            config.german_gender_ending,
        )

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

        subcategory = "d_and_i"
        category = categories[subcategory]["category"]
        endings = {
            config.german_gender_ending: config._gendereddenom_ending[
                config.german_gender_ending
            ]
        }

        list_full += gendered_denom_end(
            version, config, lang, text, category, subcategory, endings
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
            false_positives.style,
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
        words_alternatives_en["ge-singular-they"] = (
            gender_words_alternatives_GB + bias_singular_they_alternatives_GB
        )
        words_alternatives_en["style"] = style_words_alternatives_GB
        words_alternatives_en["bias"] = bias_words_alternatives_GB
        words_alternatives_en["homonym"] = homonyms_word_GB
        words_alternatives_en["abbr"] = abbreviation_GB

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
        words_alternatives_en["ge-singular-they"] = (
            gender_words_alternatives_US + bias_singular_they_alternatives_US
        )
        words_alternatives_en["style"] = style_words_alternatives_US
        words_alternatives_en["bias"] = bias_words_alternatives_US
        words_alternatives_en["homonym"] = homonyms_word_US
        words_alternatives_en["abbr"] = abbreviation_US

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
    list_full += literal_match(
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
        if config.singular_they == SingularTheyType.ALL_PRONOUNS:
            list_full += rules_based_words_phrase_matcher_en(
                version,
                config,
                lang,
                text,
                tokens,
                words_alternatives_en["ge-singular-they"],
                sentences_alternatives_en["ge"],
                rules[lang.locale]["df_gendered_sentence"],
                "gendered",
            )
        else:
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
            )
        list_full += gendered_en(
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


"""Function to change verb to -ing form in alternatives"""


def ing_ify_alternative(alternative):
    return (
        alternative.split()[0].rstrip("e")
        + "ing"
        + " "
        + " ".join(alternative.split()[1:])
    )


def ing_ify_alternatives(token, alternatives):
    if token.text.endswith("ing") and token.pos_ == "VERB":
        return [
            ing_ify_alternative(alternative).strip() for alternative in alternatives
        ]

    return alternatives


"""Function to change adjectives to -en form in alternatives"""


def get_token_type(token, token_type=None, single_word=None):
    adj_tags = {
        "ADJA",
        "ADJD",
        "ADV",
        "ADJ",
        "JJ",
        "VVPP",
        "VAPP",
        "VMPP",
        "JJR",
        "JJS",
    }
    if token.tag_ in adj_tags or token.pos_ in adj_tags:
        return "a"

    if token.pos_ == "VERB":
        return "v"

    if token.pos_ == "NOUN" or token.pos_ == "PRON":
        return "s"

    if token.pos_ == "PROPN" and single_word and token_type:
        return token_type.split(",")[0]

    return None


def check_token_type(token, token_type=None, single_word=None):
    if token_type == "adv":
        return token.pos_ == "ADV"

    return get_token_type(token, token_type, single_word) in token_type.split(",")


def add_declension(lang, text, ending):
    if lang.lang == "en" and text[-1] in ["s", "z", "h", "x"]:
        text += "e"
    if lang.lang == "de":
        if text[-1] == "s":
            text += "s"
        elif text[-1] == "e" and ending[0] == "e":
            text = text[0:-1]
        elif text[-2:] == "em":
            return text

    return text + ending


def alternative_declension(text, token_type, ending, lang, alternative):
    if ResultOut.isInspirationAlternative(text, alternative):
        return alternative

    tokens = model[lang.lang](alternative.rstrip().replace("\n", " "))

    if lang.lang == "en":
        alternative_token_types = ["v"]
    elif lang.lang == "de":
        alternative_token_types = ["v", "a"]

    new_alternative = ""
    previous = False
    for token in reversed(tokens):
        text = token.text
        if previous == False:
            alternative_token_type = get_token_type(token, token_type, len(tokens) == 1)

            if alternative_token_type in alternative_token_types:
                previous = True
                text = add_declension(lang, text, ending)

        elif is_conjunction(text):
            previous = False

        new_alternative = text + " " + new_alternative

    return new_alternative


def alternatives_declension(token, lang, alternatives):
    endings = False
    token_type = get_token_type(token)

    if lang.lang == "en" and token_type == "v":
        endings = ["s"]
    elif lang.lang == "de" and token_type:
        endings = [
            "erer",
            "eren",
            "erem",
            "eres",
            "erere",
            "erers",
            "erern",
            "ererm",
            "ste",
            "ster",
            "stes",
            "sten",
            "stem",
            "ere",
            "er",
            "en",
            "em",
            "es",
            "e",
        ]

    if endings:
        for ending in endings:
            if not token.lemma_.endswith(ending) and token.text.endswith(ending):
                return [
                    alternative_declension(
                        token.text, token_type, ending, lang, alternative
                    ).strip()
                    for alternative in alternatives
                ]

    return alternatives


"""Function to catch ending in German Denom"""


def gendered_denom_end(
    version: float,
    config: Config,
    lang,
    full_text,
    category,
    subcategory,
    endings,
    german_gender_ending=None,
):
    list_ending = []

    if not german_gender_ending:
        alternative = None

    for item, regex in endings.items():
        matches = re.finditer(r"\s(\S+)(" + regex + ")", full_text)
        for span in matches:
            if type(span) == re.Match:
                if german_gender_ending:
                    alternative = [span.group(1) + german_gender_ending]

                list_ending.append(
                    ResultOut.factory(
                        version,
                        config,
                        lang,
                        span.group(1) + span.group(2),
                        full_text,
                        category,
                        subcategory,
                        span.start() + 1,  # remove extra \S character
                        span.end(),
                        alternative,
                    )
                )

    return list_ending


def plural_or_singular_en(
    token,
    token_morph_number,
    alternative_sing,
    alternative_plur,
    subcategory,
    second_subcategory,
):
    if token_morph_number[0] == "Sing":
        return alternative_sing, subcategory
    elif token_morph_number[0] == "Plur":
        return [
            item for item in alternative_plur if item != token.text.lower()
        ], second_subcategory

    return None


def plural_or_singular_alternatives_de(
    token_morph_number, alternative_sing, alternative_plur
):
    if token_morph_number[0] == "Sing":
        return alternative_sing
    elif token_morph_number[0] == "Plur":
        return alternative_plur

    return None


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
    for token in tokens:
        for (
            word,
            word_type,
            alternative_sing,
            alternative_plur,
            subcategory,
        ) in words_alternatives_noun:
            if get_lemma_non_noun_lower_cased(token) == word and check_token_type(
                token, word_type, True
            ):
                token_morph_number = token.morph.get("Number")
                if is_number_list_empty(token_morph_number, token, full_text):
                    continue

                alternative = plural_or_singular_alternatives_de(
                    token_morph_number, alternative_sing, alternative_plur
                )

                if alternative != None:
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
                            alternative,
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

    for token in tokens:
        for word, word_type, alternative, subcategory in words_alternatives:
            if get_lemma_non_noun_lower_cased(token) == word and check_token_type(
                token, word_type, True
            ):
                alternative = alternatives_declension(token, lang, alternative)

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
                        alternative,
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
                        alternative,
                    )
                )

    return list_tokens


def ignore_binary_inclusive_gendered_denom_analysis_de(
    lang,
    tokens,
    false_positives,
):
    matcher = PhraseMatcher(model[lang.lang].vocab)

    # Only run model.make_doc to speed things up
    patterns = [model[lang.lang].make_doc(text) for text in false_positives]
    matcher.add("TerminologyList", patterns)
    matches = matcher(tokens)

    if matches.__len__() > 0:
        old_start = 0
        rest_text = []

        for match_id, start, end in matches:
            part = tokens[old_start:start]
            rest_text.append(part.text)
            old_start = end

        docs = list(model[lang.lang].pipe(rest_text))
        tokens = Doc.from_docs(docs)

    return tokens


def match_binary_inclusive_gendered_denom_analysis_de(
    config: Config, false_positives, full_text, token, category, subcategory
):
    text = token.text
    start = token.idx
    if not ResultOut.genderedRolesFormatBinary(config.gendered_roles_format):
        for false_positive in false_positives:
            if not false_positive.endswith(text):
                continue

            new_start = start - len(false_positive.removesuffix(text))
            if false_positive == full_text[new_start : new_start + len(false_positive)]:
                start = new_start
                text = false_positive

                subcategory = "gendered_denominations_ending"
                category = categories[subcategory]["category"]
                break

    return text, start, category, subcategory


def find_article(token):
    for masculine, feminine, neuter, plural in articles:
        if token.text.lower() == masculine:
            return masculine, feminine, neuter, plural

    return None, None, None, None


def gendered_denom_analysis_de(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    gender_words_alternatives,
    false_positives,
):
    category = "gendered"

    if ResultOut.genderedRolesFormatBinary(config.gendered_roles_format):
        tokens = ignore_binary_inclusive_gendered_denom_analysis_de(
            lang, tokens, false_positives
        )

    list_tokens = []
    for i in range(len(tokens)):
        for (
            word,
            word_type,
            alternatives_sing,
            alternatives_plur,
            alternatives_all,
            subcategory,
        ) in gender_words_alternatives:
            if tokens[i].lemma_ == word and check_token_type(
                tokens[i], word_type, True
            ):
                token_morph_number = tokens[i].morph.get("Number")
                if is_number_list_empty(token_morph_number, tokens[i], full_text):
                    alternatives = alternatives_all
                else:
                    alternatives = plural_or_singular_alternatives_de(
                        token_morph_number, alternatives_sing, alternatives_plur
                    )

                if alternatives != None:
                    (
                        text,
                        start,
                        category,
                        subcategory,
                    ) = match_binary_inclusive_gendered_denom_analysis_de(
                        config,
                        false_positives,
                        full_text,
                        tokens[i],
                        category,
                        subcategory,
                    )

                    if i > 0 and token_morph_number[0] == "Sing":
                        alternatives_with_article = []
                        masculine, feminine, neuter, plural = find_article(
                            tokens[i - 1]
                        )

                        if masculine != None:
                            for alternative in alternatives:
                                if "~" in alternative:
                                    article_alternative = feminine + "~" + masculine
                                else:
                                    if "---" in alternative:
                                        (
                                            alternative,
                                            alternative_context,
                                        ) = alternative.split("---")
                                        alternative = alternative.strip()

                                    words = alternative.split()
                                    gender = get_gender_of_word(words[-1])

                                    if gender["definite_article"] == "der":
                                        article_alternative = masculine
                                    elif gender["definite_article"] == "das":
                                        article_alternative = neuter
                                    elif gender["definite_article"] == "die" or alternative.endswith("in"):
                                        article_alternative = feminine

                                alternatives_with_article.append(
                                    article_alternative + " " + alternative
                                )

                            alternatives = alternatives_with_article
                            start = tokens[i - 1].idx
                            text = tokens[i - 1].text + " " + text

                    list_tokens.append(
                        ResultOut.factory(
                            version,
                            config,
                            lang,
                            text,
                            full_text,
                            category,
                            subcategory,
                            start,
                            None,
                            alternatives,
                        )
                    )

    return list_tokens


# Unified function for Empty words false positives and rules
def is_conjunction(full_text, start=0):
    if full_text in ["und", "oder", "and", "or"]:
        return True

    preceeding_text = full_text[max(0, start - 5) : start]
    return (
        re.search(r"^ *$", preceeding_text) != None
        or re.search(r"[.!?:,]\s*$", preceeding_text, re.MULTILINE) != None
    )


def style_word_analysis_de(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    terms,
    style_words_alternatives,
    style_sentences_alternatives,
    false_positives,
):
    category = "style"
    list_tokens = []

    # Phrase matcher part to handle False positives with two words and special simbols
    matcher = PhraseMatcher(model[lang.lang].vocab)

    # Only run model.make_doc to speed things up
    patterns = [model[lang.lang].make_doc(text) for text in terms]
    matcher.add("TerminologyList", patterns)

    for i in range(len(tokens)):
        # check if the user query have false positives
        if is_false_positive(tokens[i].lemma_, false_positives):
            # recognise if there is Name of organisation or geographical name in the query
            if len(tokens.ents) > 0:
                continue

        if tokens[i].lemma_ == "aber" and is_conjunction(full_text, tokens[i].idx):
            continue

        for word, word_type, alternative, subcategory in style_words_alternatives:
            if tokens[i].lemma_ == word and check_token_type(
                tokens[i], word_type, True
            ):
                alternative = alternatives_declension(tokens[i], lang, alternative)

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
                        alternative,
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
                        alternative,
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
            word_type,
            alternative_sing,
            alternative_plur,
            subcategory,
        ) in bias_words_alternatives_noun:
            if get_lemma_non_noun_lower_cased(token) == word and check_token_type(
                token, word_type, True
            ):
                token_morph_number = token.morph.get("Number")
                if is_number_list_empty(token_morph_number, token, full_text):
                    continue

                alternative = plural_or_singular_alternatives_de(
                    token_morph_number, alternative_sing, alternative_plur
                )

                if alternative != None:
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
                            alternative,
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
        for word, word_type, alternative, subcategory in words_alternatives:
            if get_lemma_non_noun_lower_cased(token) == word and check_token_type(
                token, word_type, True
            ):
                alternative = alternatives_declension(token, lang, alternative)

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
                        alternative,
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
                        alternative,
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
        for word, word_type in df:
            if get_lemma_non_noun_lower_cased(token) == word and check_token_type(
                token, word_type, True
            ):
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
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    df,
    category,
    subcategory,
):
    list_tokens = []
    for token in tokens:
        for word, word_type in df:
            if get_lemma_non_noun_lower_cased(token) == word and check_token_type(
                token, word_type, True
            ):
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
        for word, word_type, alternative, subcategory in words_alternatives:
            if get_lemma_lower_cased(token) == word and check_token_type(
                token, word_type, True
            ):
                alternative = ing_ify_alternatives(token, alternative)
                alternative = alternatives_declension(token, lang, alternative)

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
                        alternative,
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
                        alternative,
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

            if token.lemma_ == word and check_token_type(token, word_type, True):
                alternative = ing_ify_alternatives(token, alternative)

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
                        alternative,
                    )
                )

    return list_tokens


# function to find exact match for abbreviations and term replacements
def literal_match(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    df_term,
    term_list,
):
    list_tokens = []
    # Phrase matcher part to handle False positives with two words and special simbols
    matcher = PhraseMatcher(model[lang.lang].vocab)

    # Only run model.make_doc to speed things up
    patterns = [model[lang.lang].make_doc(text) for text in list(df_term["Lemma"])]
    matcher.add("TerminologyList", patterns)

    matches = matcher(tokens)
    for match_id, start, end in matches:
        for (
            term,
            category,
            subcategory,
            alternative,
            *explanation,
        ) in term_list:
            if not is_sub_category_enabled(config, subcategory):
                continue
            span = tokens[start:end]
            if span.text == term:
                url = None
                icon = None
                explanation_text = None

                if (
                    isinstance(explanation, list)
                    and len(explanation)
                    and isinstance(explanation[0], dict)
                ):
                    explanation_text = (
                        explanation[0]["text"] if "text" in explanation[0] else None
                    )
                    url = explanation[0]["url"] if "url" in explanation[0] else None
                    icon = explanation[0]["icon"] if "icon" in explanation[0] else None

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
                        alternative,
                        None,
                        explanation_text,
                        url,
                        icon,
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
            word_type,
            alternative_sing,
            alternative_plur,
            subcategory,
            second_subcategory,
        ) in gendered_words_alternatives:
            if get_lemma_lower_cased(token) == word and check_token_type(
                token, word_type, True
            ):
                token_morph_number = token.morph.get("Number")
                if is_number_list_empty(token_morph_number, token, full_text):
                    continue

                alternative, subcategory = plural_or_singular_en(
                    token,
                    token_morph_number,
                    alternative_sing,
                    alternative_plur,
                    subcategory,
                    second_subcategory,
                )

                if alternative != None:
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
                            alternative,
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
        for word, word_type, subcategory in inclusive_words_alternatives_en:
            if get_lemma_lower_cased(token) == word and check_token_type(
                token, word_type, True
            ):
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
