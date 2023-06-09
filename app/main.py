# from blackfire import probe

# probe.initialize()
# probe.enable()

import re
import uvicorn
import json
import secrets
import aiohttp
from typing import Optional, Union, List
from collections import defaultdict
from pydantic import parse_obj_as

import os
import fasttext

from spacy.matcher import PhraseMatcher, Matcher
import pandas as pd

from inflex import Noun, Verb, Adjective

from fastapi import (
    FastAPI,
    Request,
    Response,
    HTTPException,
    Depends,
    Query,
    status,
)

from contextlib import asynccontextmanager
from fastapi.encoders import jsonable_encoder
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

from fastapi_microsoft_identity import validate_scope, get_token_claims

import secure

import emoji
from cmp_version import VersionString

from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt.app.async_app import AsyncApp
from slack_sdk import WebClient
from slack_sdk.models.blocks import (
    SectionBlock,
    MarkdownTextObject,
)
from slack_bolt import Ack, Respond
from slack_sdk.web.async_client import AsyncWebClient

from app.models import (
    Config,
    GenderedRolesFormatType,
    GermanGenderEndingType,
    LangType,
    Language,
    GermanLanguageRequest,
    EnglishLanguageRequest,
    RequestIn,
    Result,
    ResultOut,
    ResultsOut,
    UserConfRequest,
    OrganizationConfRequest,
    ConfResponse,
    UserConfResponse,
    RuleConfig,
    ResultConf,
    ErrorMessage,
    PrettyJSONResponse,
)
from app.lang_detection import get_lang_detection
from app.categories import (
    get_categories,
    get_category,
    is_category_inclusive,
    get_proficiency_level,
)
from app.settings import get_settings
from app.logger import set_up_logger
from app.redis_setup import set_up_redis
from app.azure_ad_b2c import initialize_aadb2c
from app.model import fetch_nlp_model
from app.rules import fetch_rules
from app.sentry import set_up_sentry_sdk

# probe.end()

version = "1.43.12"

categories = get_categories()
settings = get_settings()
logging = set_up_logger(settings)
sentry_sdk = set_up_sentry_sdk(version, settings)
redis = set_up_redis(settings)
initialize_aadb2c(settings)

logging.debug("app started with settings: %s", settings)

if len(settings.models) > 0:
    model = {}
    for spacy_model in settings.models:
        lang = spacy_model[0:2]
        if lang in settings.langs:
            model[lang] = fetch_nlp_model(lang, spacy_model)

    rules = fetch_rules(settings.langs)

if settings.fasttext:
    pretrained_lang_model = os.getcwd() + "/training_data/lid.176.bin"
    fasttext_model = fasttext.load_model(pretrained_lang_model)

if (
    settings.slack_bot_token is not None and settings.slack_signing_secret is not None
):  # pragma: no cover
    bolt = AsyncApp(
        token=settings.slack_bot_token, signing_secret=settings.slack_signing_secret
    )
else:
    bolt = AsyncApp(
        signing_secret="valid",
        client=AsyncWebClient(
            token="valid_token",
            base_url="http://localhost",
        ),
    )

bolt_handler = AsyncSlackRequestHandler(bolt)


@bolt.command("/witty")
async def handle_command_witty(
    body: dict, ack: Ack, respond: Respond, client: WebClient
):  # pragma: no cover
    await ack()

    user_request_in = RequestIn(client="slack-1.0.0", text=body["text"])
    text, lang, limit_reached = fetch_text(user_request_in)

    if lang is None:
        await respond(f"Witty could not determine a language for '{text}'.")
        return

    version = 2.3
    configs = {}

    try:
        user = await client.users_info(user=body["user_id"])
        configs = await fetch_configs_for_request(
            version, user_request_in, user.data["user"]["profile"]["email"]
        )
    except KeyError:
        pass

    if configs == {} and settings.slack_organization_id:
        configs = await fetch_organization_configs_for_request(
            version, user_request_in, settings.slack_organization_id
        )

    user_request_in.config.__setattr__("alternatives_max_count", None)
    results = await apply_language_rules(
        version, user_request_in.client, user_request_in.config, configs, lang, text
    )

    analyzed_text = f"*Analyzed*: {text}"
    if limit_reached:
        analyzed_text += " (text length limit reached)"

    blocks = [
        SectionBlock(
            block_id="text",
            text=MarkdownTextObject(text=analyzed_text),
        ),
        SectionBlock(
            block_id="details",
            text=MarkdownTextObject(
                text=f"*Language*: {lang.lang}, *Number of Issues Detected*: {len(results)}"
            ),
        ),
    ]

    if len(results):
        for i, result in enumerate(results):
            issue_text = f"#{i+1} Matched Text: {result.text} (category {result.category}, proficiency_level {result.proficiency_level})\n"

            if result.explanation.icon:
                issue_text += f"{result.explanation.icon} "

            if result.explanation.url:
                issue_text += f"<{result.explanation.url}|{result.explanation.text}>"
            else:
                issue_text += f"{result.explanation.text}"

            if result.explanation.context:
                issue_text += f" ({result.explanation.context})"

            blocks.append(
                SectionBlock(
                    block_id=f"match{i}",
                    text=MarkdownTextObject(text=issue_text),
                )
            )

            if len(result.alternatives):
                alternatives = ""
                for alternative in result.alternatives:
                    if alternative.remove:
                        alternatives += f"\n• ~{alternative.text}~"
                    else:
                        alternatives += f"\n• {alternative.text}"

                    if alternative.context:
                        alternatives += f"- ({alternative.context})"

                blocks.append(
                    SectionBlock(
                        block_id=f"alternatives{i}",
                        text=MarkdownTextObject(text=alternatives),
                    )
                )

    await respond(blocks=blocks)


session = None
ssl_session = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global session
    global ssl_session

    session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False))
    ssl_session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=True))

    yield

    await session.close()
    await ssl_session.close()


app = FastAPI(
    title="Witty NLP API",
    version=version,
    terms_of_service=settings.terms_of_service,
    contact=settings.contact,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

security = HTTPBasic(auto_error=False)

csp = secure.ContentSecurityPolicy().set("default-scr 'self' cdn.jsdelivr.net")
xfo = secure.XFrameOptions().deny()
xxp = secure.XXSSProtection().set("1; mode=block")

secure_headers = secure.Secure(csp=csp, xfo=xfo, xxp=xxp)


@app.middleware("http")
async def set_secure_headers(request, call_next):
    response = await call_next(request)
    secure_headers.framework.fastapi(response)
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# https://languagetool.org/development/api/org/languagetool/rules/Categories.html
lt_style_categories = [
    "FALSE_FRIENDS",
    "REDUNDANCY",
    "REGIONALISMS",
    "REPETITIONS_STYLE",
    "SEMANTICS",
    "STYLE",
]


def fetch_current_username(
    credentials: Optional[HTTPBasicCredentials] = Depends(security),
):  # pragma: no cover
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


@app.post("/slack/commands")
async def post_slack_commands(request: Request):  # pragma: no cover
    return await bolt_handler.handle(request)


# debugging routes
@app.post(
    "/exception",
    include_in_schema=not settings.is_prod,
)
async def post_exception(
    request: Request,
    user_request_in: RequestIn,
    username: str = Depends(fetch_current_username),
):  # pragma: no cover
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=user_request_in.text
    )


@app.get("/health")
async def get_health(check_external: bool = False):
    health = {}

    langs = {
        "en": "Hello guys",
        "de": "Hallo Kunde",
    }

    for spacy_model in settings.models:
        lang = spacy_model[0:2]
        try:
            fetch_tokens(lang, langs[lang])
            health["model_" + lang] = True
        except:
            health["model_" + lang] = False

    if check_external:
        languagetool_health = await fetch_json_get(
            settings.languagetool_api + "/healthcheck",
            {},
            {},
            "LanguageTool",
            settings.languagetool_verify_ssl,
            False,
        )

        health["spelling"] = languagetool_health == "OK"
        health["config"] = redis.ping()

    content = jsonable_encoder(health)

    for key in health:
        if not health[key]:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=content,
            )

    return content


@app.get("/lt", include_in_schema=not settings.is_prod)
def get_lt(username: str = Depends(fetch_current_username)):
    return settings.languagetool_api


@app.get("/settings", include_in_schema=not settings.is_prod)
def get_lt(username: str = Depends(fetch_current_username)):
    return settings


@app.get("/docs", include_in_schema=False)
def get_swagger_documentation(
    username: str = Depends(fetch_current_username),
    include_in_schema=not settings.is_prod,
):  # pragma: no cover
    return get_swagger_ui_html(openapi_url="/openapi.json", title="docs")


@app.get("/openapi.json", include_in_schema=False)
def get_openapi_json(
    username: str = Depends(fetch_current_username),
):  # pragma: no cover
    return get_openapi(title=app.title, version=app.version, routes=app.routes)


# public routes
@app.get("/", include_in_schema=False)
def get_root():
    if not settings.is_prod and settings.testing == False:  # pragma: no cover
        return RedirectResponse(url="/docs", status_code=302)

    return "Witty NLP API: https://witty.works"


@app.get(
    "/save_openapi_json",
    include_in_schema=not settings.is_prod,
)
def get_save_openapi_json(
    username: str = Depends(fetch_current_username),
):  # pragma: no cover
    openapi_data = app.openapi()
    for path in openapi_data["paths"].copy():
        if not "v2.0" in path:
            del openapi_data["paths"][path]

    with open("openapi.json", "w") as file:
        json.dump(openapi_data, file, indent=4, sort_keys=True)


@app.get(
    "/debug/german_gender_ending",
    include_in_schema=not settings.is_prod,
    response_class=PrettyJSONResponse,
)
def get_german_gender_ending(
    alternative: str,
    german_gender_ending: GermanGenderEndingType = None,
    username: str = Depends(fetch_current_username),
):
    alternative_variations = set()

    german_gender_endings = Config._gendereddenom_ending.keys()
    if german_gender_ending is not None:
        german_gender_endings = [german_gender_ending]

    for german_gender_ending in german_gender_endings:
        alternative_variations.update(
            ResultOut.getAlternativeVariations(
                GenderedRolesFormatType.BOTH, german_gender_ending, alternative
            )
        )

    return alternative_variations


@app.get(
    "/debug/configs",
    include_in_schema=not settings.is_prod,
    dependencies=[Depends(HTTPBearer(auto_error=False))],
)
async def get_config_debug(
    user_email: str,
    username: str = Depends(fetch_current_username),
):  # pragma: no cover
    user_request_in = RequestIn(text="")
    version = 2.3

    try:
        configs = await fetch_user_organization_configs(user_email)
        result_configs = await fetch_configs_for_request(
            version, user_request_in, user_email
        )
        del result_configs["organization_config"]
        del result_configs["organization_domains"]
        del result_configs["organization_false_positives"]
        del result_configs["organization_term_replacements"]

    except HTTPException:
        configs = None
        result_configs = None

    return {
        "configs": configs,
        "result_configs": result_configs,
        "user_request_in": user_request_in,
    }


@app.post(
    "/debug/auth",
    include_in_schema=not settings.is_prod,
    dependencies=[Depends(HTTPBearer(auto_error=False))],
)
async def post_auth_debug(
    request: Request, user_request_in: RequestIn
):  # pragma: no cover
    user_email = fetch_user(request)
    if not user_email:
        return user_email

    version = 2.3
    configs = await fetch_configs_for_request(version, user_request_in, user_email)

    if "authorization" in request.headers and request.headers[
        "authorization"
    ].lower().startswith("bearer"):
        claim = get_token_claims(request)
    else:
        claim = "using auth token override"

    return {
        "claim": claim,
        "configs": configs,
        "user_request_in": user_request_in,
    }


@app.post(
    "/v2.0/auth",
    response_model=Union[ResultConf, dict, None],
    response_model_exclude_none=True,
    dependencies=[Depends(HTTPBearer(auto_error=False))],
)
async def post_auth_2_0(request: Request):
    user_email = fetch_user(request)
    if not user_email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
        )

    version = 2.3
    configs = await fetch_configs_for_request(version, RequestIn(text=""), user_email)
    if configs == {}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
        )

    if "config" in configs:
        configs["config"] = bc_old_categories(configs["config"])

    if "organization_config" in configs:
        configs["organization_config"] = bc_old_categories(
            configs["organization_config"]
        )

    config = fetch_result_conf(configs)

    if "team_analytics" in configs and not configs["team_analytics"]:
        config.organization_id = None

    return config


def bc_old_categories(config):
    # BC code
    old_categories = ["style", "inclusive", "orthography"]
    for old_category in old_categories:
        if old_category in config and config[old_category] is not None:
            continue

        if old_category in config["categories"]:
            config[old_category] = config["categories"][old_category]
        else:
            config[old_category] = {
                "value": False,
                "status": "suggestion",
            }

    return config


@app.get(
    "/debug/spacy",
    include_in_schema=not settings.is_prod,
    response_class=PrettyJSONResponse,
)
async def get_debug_spacy(
    text: str,
    lang: LangType,
    username: str = Depends(fetch_current_username),
):
    if settings.language_endpoint_urls[lang]:  # pragma: no cover
        url = "/debug/spacy"
        payload = {
            "text": text,
            "lang": lang.value,
        }

        return await fetch_json_from_language_service(lang, url, payload, True)

    results = []
    tokens = fetch_tokens(lang, text)
    for token in tokens:
        results.append(
            {
                "text": token.text,
                "lemma": token.lemma_,
                "start": token.idx,
                "tag": token.tag_,
                "pos": token.pos_,
                "dep": token.dep_,
                "word_types": fetch_word_types(lang, token),
                "morph": token.morph.to_dict(),
                "is_emoji": token._.is_emoji,
                "emoji_desc": token._.emoji_desc,
            }
        )

    return results


@app.get(
    "/debug/german_noun",
    include_in_schema=not settings.is_prod,
    response_class=PrettyJSONResponse,
)
async def get_debug_german_noun(
    word: str,
    genus_only: bool = False,
    username: str = Depends(fetch_current_username),
):
    return german_noun_analysis(word, genus_only)


@app.post(
    "/german",
    include_in_schema=not settings.is_prod,
    response_class=JSONResponse,
)
async def german(request: Request, german_request: GermanLanguageRequest):
    if not settings.language_endpoint_enabled_de and (
        not settings.testing or "x-german" not in request.headers
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
        )

    check_version(german_request.version)

    lang = Language(german_request.locale)

    return await german_rules(
        german_request.version,
        german_request.client,
        german_request.config,
        german_request.configs,
        lang,
        german_request.text,
    )


@app.post(
    "/english",
    include_in_schema=not settings.is_prod,
    response_class=JSONResponse,
)
async def english(request: Request, english_request: EnglishLanguageRequest):
    if not settings.language_endpoint_enabled_en and (
        not settings.testing or "x-english" not in request.headers
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
        )

    check_version(english_request.version)

    lang = Language(english_request.locale)

    return await english_rules(
        english_request.version,
        english_request.client,
        english_request.config,
        english_request.configs,
        lang,
        english_request.text,
    )


@app.post(
    "/debug/check",
    response_model=Union[ResultsOut, Result],
    response_model_exclude_none=True,
    dependencies=[Depends(HTTPBearer(auto_error=False))],
    include_in_schema=not settings.is_prod,
)
async def post_debug_check(
    request: Request,
    response: Response,
    user_request_in: RequestIn,
    username: str = Depends(fetch_current_username),
):
    return await check(request, response, user_request_in, None)


@app.post(
    "/v2.2/check",
    response_model=Union[ResultsOut, Result],
    response_model_exclude_none=True,
    dependencies=[Depends(HTTPBearer(auto_error=False))],
)
async def post_check_v2_2(
    request: Request,
    response: Response,
    user_request_in: RequestIn,
):
    return await check(request, response, user_request_in, 2.2)


@app.post(
    "/v2.3/check",
    response_model=Union[ResultsOut, Result],
    response_model_exclude_none=True,
    dependencies=[Depends(HTTPBearer(auto_error=False))],
)
async def post_check_v2_3(
    request: Request,
    response: Response,
    user_request_in: RequestIn,
):
    return await check(request, response, user_request_in, 2.3)


# data exchange routes
@app.get("/lemmatize")
async def lemmatize(
    text: str,
    lang: LangType = None,
    locale: LangType
    | None = Query(
        default=None,
        description="Deprecated in favor of 'lang'",
        deprecated=True,
    ),
    username: str = Depends(fetch_current_username),
):
    if lang == None:
        if locale == None:
            raise HTTPException(
                status_code=422,
                detail="Provide the 'lang' query parameter with a value of 'en' or 'de'.",
            )

        lang = locale

    if settings.language_endpoint_urls[lang]:  # pragma: no cover
        url = "/lemmatize"
        payload = {
            "text": text,
            "lang": lang.value,
        }

        return await fetch_json_from_language_service(lang, url, payload, True)

    tokens = fetch_tokens(lang, text)
    if len(tokens) != 1:
        return None

    return tokens[0].lemma_


@app.post(
    "/organization/configs",
    response_model=ConfResponse,
    response_model_exclude_none=True,
)
async def post_organization_configs(
    organization_configs: OrganizationConfRequest,
    username: str = Depends(fetch_current_username),
):
    redis.set(organization_configs.id, organization_configs.json())

    return organization_configs


@app.delete(
    "/organization/configs",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_organiztion_configs(
    organization_id: str,
    username: str = Depends(fetch_current_username),
):
    redis.delete(organization_id)


@app.get(
    "/organization/configs",
    response_model=ConfResponse,
    response_model_exclude_none=True,
    responses={404: {"model": ErrorMessage}},
)
async def get_organization_configs(
    organization_id: str,
    username: str = Depends(fetch_current_username),
):
    return await fetch_organization_configs_from_redis(organization_id)


@app.post(
    "/user/configs",
    response_model=UserConfResponse,
    response_model_exclude_none=True,
)
async def post_user_configs(
    user_configs: UserConfRequest, username: str = Depends(fetch_current_username)
):
    redis.set(user_configs.email, user_configs.json())

    return user_configs


@app.delete(
    "/user/configs",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_user_configs(
    email: str,
    username: str = Depends(fetch_current_username),
):
    redis.delete(email)


@app.get(
    "/user/configs",
    response_model=UserConfResponse,
    response_model_exclude_none=True,
    responses={404: {"model": ErrorMessage}},
)
async def get_user_configs(
    email: str,
    username: str = Depends(fetch_current_username),
):
    configs = await fetch_user_organization_configs(email)

    if not configs or type(configs) is not dict:
        return JSONResponse(
            status_code=404, content={"message": "User configs not found"}
        )

    return configs


# Functions
async def fetch_organization_configs_from_redis(
    organization_id: str,
):
    configs = redis.get(organization_id)
    if not configs:
        raise HTTPException(status_code=404, detail="Organization configs not found")

    return json.loads(configs)


async def fetch_user_configs_from_redis(
    email: str,
):
    configs = redis.get(email)
    if not configs:
        raise HTTPException(status_code=404, detail="User configs not found")

    return json.loads(configs)


async def fetch_user_organization_configs(email: str):
    configs = await fetch_user_configs_from_redis(email)

    configs["plan"] = "witty_free"
    configs["organization_name"] = None
    configs["organization_config_hash"] = None
    configs["organization_domains"] = None

    if "organization_id" in configs and configs["organization_id"] is not None:
        try:
            organization_configs = await fetch_organization_configs_from_redis(
                configs["organization_id"]
            )

            configs["plan"] = organization_configs["plan"]
            configs["organization_name"] = organization_configs["name"]

            if "config_hash" in organization_configs:
                configs["organization_config_hash"] = organization_configs[
                    "config_hash"
                ]
            else:
                configs["organization_config_hash"] = None

            if "domains" in organization_configs:
                configs["organization_domains"] = organization_configs["domains"]
            else:
                configs["organization_domains"] = {}

            configs["organization_config"] = organization_configs["config"]
            configs["organization_term_replacements"] = organization_configs[
                "term_replacements"
            ]
            configs["organization_false_positives"] = organization_configs[
                "false_positives"
            ]
        except HTTPException:
            pass
    else:
        configs["organization_id"] = None

    return configs


def is_token_singular(lang, token):
    number = token.morph.get("Number")
    if number:
        return "Sing" in number

    if lang == "en" and token.text[-1:] == "s":
        return False

    return None


def is_token_plural(lang, token):
    is_singular = is_token_singular(lang, token)
    if is_singular is None:
        return None

    return not is_singular


# BC code
def get_bc_disabled_categories(disable_style, disable_inclusive, advanced_enabled=True):
    old_style_category = [
        "abbreviation",
        "anglicism",
        "exaggerating",
        "false_friends",
        "filler",
        "formality",
        "general_style",
        "hollow",
        "redundancy",
        "regionalisms",
        "repetitions_style",
        "semantics",
        "plain_language",
        "style",
    ]

    disabled_categories = []

    categories = get_categories()
    for category in categories:
        category_data = categories[category]
        if (
            "proficiency_level" not in category_data
            or category_data["proficiency_level"] == "openly_discriminating"
        ):
            continue

        is_inclusive = is_category_inclusive(category)
        if (is_inclusive and disable_inclusive) or (
            not is_inclusive and disable_style and category in old_style_category
        ):
            disabled_categories.append(category)
            disabled_categories.append("advanced_" + category)
        elif not advanced_enabled:
            disabled_categories.append("advanced_" + category)

    if disable_inclusive:
        disabled_categories.append("inclusive")

    return disabled_categories


def apply_configs(
    version: float,
    user_request_in: RequestIn,
    configs: dict,
    plan: str,
    overwrite_enabled_categories: bool = True,
):
    disabled_categories = user_request_in.config.disabled_categories

    # BC code - old browser extension
    disable_inclusive = disable_style = None
    if version < 2.3:
        disable_inclusive = "inclusive" in disabled_categories
        disable_style = "style" in disabled_categories

    for config in configs:
        data = configs[config]
        if data is None:
            continue

        if config == "categories":
            for category in data:
                category_data = data[category]
                if category_data["status"] != "force":
                    continue

                if category_data["value"]:
                    if category in disabled_categories:
                        disabled_categories.remove(category)
                elif (
                    category not in disabled_categories and overwrite_enabled_categories
                ):
                    disabled_categories.append(category)
        elif config == "store_context":
            if (
                plan == "witty_teams"
                and data["status"] == "force"
                and not data["value"]
            ):
                user_request_in.config.__setattr__("store_context", False)
        elif data["status"] == "force":
            user_request_in.config.__setattr__(config, data["value"])

    # BC code - old browser extension
    if "categories" in configs and disable_style or disable_inclusive:
        disabled_categories = get_bc_disabled_categories(
            disable_style, disable_inclusive
        )

    user_request_in.config.__setattr__("disabled_categories", disabled_categories)
    user_request_in.config.__setattr__("plan", plan)


async def fetch_configs_for_request(
    version: float, user_request_in: RequestIn, user_email=Optional[str]
):
    user_request_in.config.__setattr__("store_context", True)
    user_request_in.config.__setattr__("plan", None)
    user_request_in.config.__setattr__(
        "alternatives_max_count", settings.alternatives_max_count
    )

    if not user_email:
        return {}

    try:
        configs = await fetch_user_organization_configs(user_email)
    except HTTPException:
        configs = None

    if not configs or type(configs) is not dict:
        return {}

    apply_configs(version, user_request_in, configs["config"], configs["plan"])

    if "organization_config" in configs:
        apply_configs(
            version,
            user_request_in,
            configs["organization_config"],
            configs["plan"],
            settings.overwrite_enabled_user_categories,
        )

        configs["term_replacements"] |= configs["organization_term_replacements"]
        configs["false_positives"] = list(
            set(configs["false_positives"] + configs["organization_false_positives"])
        )

    return configs


async def fetch_organization_configs_for_request(
    version: float, user_request_in: RequestIn, organization_id=Optional[str]
):
    user_request_in.config.__setattr__("store_context", True)

    if not organization_id:
        return {}

    try:
        configs = await fetch_organization_configs_from_redis(organization_id)
    except HTTPException:
        return {}

    for config in configs["configs"]:
        if configs["configs"][config]["status"] == "suggestion":
            configs["configs"][config]["status"] = "force"

    apply_configs(version, user_request_in, configs["config"], configs["plan"])

    return configs


def fetch_email_from_claims(claims):
    try:  # pragma: no cover
        if claims["aud"] != settings.aadb2c_client_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="access token does not match client id",
            )

        if "email" in claims:
            return claims["email"]

        if "emails" in claims and len(claims["emails"]) > 0:
            return claims["emails"][0]

    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="access token does not map to email",
        )

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="no email found in claim",
    )


def fetch_user(request: Request):
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

        return fetch_email_from_claims(claims)

    if settings.testing:
        if "x-auth" in request.headers:
            return request.headers["x-auth"]
        if settings.redis_default_user:  # pragma: no cover
            return settings.redis_default_user

    return None


def fetch_text(user_request_in):
    text = user_request_in.text
    limit_reached = len(text) > settings.text_max_length
    if limit_reached:
        text = text[0 : settings.text_max_length]
        text = text.rsplit(" ", 1)[0]

    lang_detection = get_lang_detection(fasttext_model)
    locale = lang_detection.get_locale(
        text,
        user_request_in.lang,
        user_request_in.config.preferred_languages,
        user_request_in.config.preferred_variants,
    )

    if locale is None:
        lang = None
    else:
        lang = Language(locale)

    return text, lang, limit_reached


def check_version(version: float):
    if version != 2.2 and version != 2.3:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Version not supported: " + str(version),
        )


async def check(
    request: Request,
    response: Response,
    user_request_in: RequestIn,
    version: Optional[float],
):
    if version is not None:
        check_version(version)

        user_email = fetch_user(request)
        configs = await fetch_configs_for_request(version, user_request_in, user_email)
    else:
        # debug
        version = 2.3
        configs = {"categories": {}}
        apply_configs(version, user_request_in, configs, "witty_teams")

    text, lang, limit_reached = fetch_text(user_request_in)

    if lang is None:
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        results = Result.factory("Language could not be determined")
        language = None
        configs = {}
    else:
        results = await apply_language_rules(
            version, user_request_in.client, user_request_in.config, configs, lang, text
        )

        language = lang.lang

    if isinstance(results, Result):
        return results

    notifications = None
    if "notifications" in configs and configs["notifications"] > 0:
        notifications = configs["notifications"]

    has_consented_to_mailing = None
    if "has_consented_to_mailing" in configs:
        has_consented_to_mailing = configs["has_consented_to_mailing"]

    return ResultsOut(
        results=results,
        language=language,
        limit_reached=limit_reached,
        config_changed=fetch_config_change(configs, user_request_in),
        notifications=notifications,
        has_consented_to_mailing=has_consented_to_mailing,
    )


def fetch_config_change(
    configs: dict,
    user_request_in: Optional[RequestIn] = None,
):
    if not user_request_in:
        return True

    if (
        "config_hash" in configs
        and user_request_in.config_hash != configs["config_hash"]
    ):
        return True

    if (
        "organization_config_hash" in configs
        and user_request_in.organization_config_hash
        != configs["organization_config_hash"]
    ):
        return True

    return None


def fetch_result_conf(configs: dict):
    if "config" not in configs:
        return None

    if "organization_config" in configs:
        organization_config = RuleConfig.parse_obj(configs["organization_config"])
    else:
        organization_config = None

    plan = configs["plan"]

    config = RuleConfig.parse_obj(configs["config"])

    return ResultConf(
        id=configs["id"],
        name=configs["name"],
        plan=plan,
        config=config,
        organization_id=configs["organization_id"],
        organization_name=configs["organization_name"],
        organization_config=organization_config,
        domains=configs["domains"],
        organization_domains=configs["organization_domains"],
        config_hash=configs["config_hash"],
        organization_config_hash=configs["organization_config_hash"],
    )


def fetch_alternatives(match):
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
    version: float, config: Config, lang: Language, full_text: str, offsets, result
):
    list_results = []
    ignore = ["@", "#"]

    gendered_denom = lang.lang == "de" and ResultOut.genderedRolesFormatInclusive(
        config.gendered_roles_format
    )

    for match in result["matches"]:
        start = int(match["offset"])
        end = start + int(match["length"])

        if offsets and len(offsets["utf16_chars"]) > start:
            start = offsets["utf16_chars"][start]

        if offsets and len(offsets["utf16_chars"]) > end:
            end = offsets["utf16_chars"][end]

        text = full_text[start:end]

        # Ignore capitalization after German salutation
        if match["rule"]["category"]["id"] == "TYPOS":
            subtext = (
                full_text[0:start]
                .lstrip()
                .lower()
                .replace("'", "")
                .replace("'", "")
                .split("\n")
            )
            if len(subtext) == 1 and any(
                substring.lower() + " " in subtext[0]
                for substring in rules[lang.lang]["salutations"]
            ):
                continue

        if (
            lang.lang == "de"
            and config.german_gender_ending == ":in"
            and match["rule"]["id"] == "LEERZEICHEN_HINTER_DOPPELPUNKT"
            and full_text[start + 1 : end] in rules["de"]["male_articles"]
        ):
            continue

        # ignore full_text that starts with @ or #
        if text[0:1] in ignore or (
            start > 0 and full_text[start - 1 : start] in ignore
        ):
            continue

        # ignore german gender ending as spelling mistakes
        if gendered_denom and has_gender_denom_ending(text, full_text, start, config):
            continue

        try:
            subcategory = match["rule"]["category"]["id"]

            if match["rule"]["id"] in ["SONDERZEICHEN", "ROEMISCHE_ZAHL"]:
                continue
            elif subcategory in lt_style_categories:
                subcategory = "style"
            elif subcategory == "PLAIN_ENGLISH":
                subcategory = "advanced_plain_language"
            elif subcategory == "DIFFICULT_WORDS":
                if match["rule"]["id"] == "ABKUERZUNG":
                    subcategory = "abbreviation"
                elif (
                    match["rule"]["id"] == "ANGLIZISMEN"
                    or "Fremdwörter" in match["message"]
                ):
                    subcategory = "advanced_anglicism"
                else:
                    subcategory = "plain_language"
            elif match["rule"]["category"]["name"] == "Leichte Sprache":
                subcategory = "advanced_plain_language"
            else:
                subcategory = subcategory.lower()
                if subcategory == "style":
                    subcategory = "general_style"
                elif subcategory not in categories:
                    subcategory = "orthography"
        except KeyError:
            subcategory = "orthography"

        if not is_sub_category_enabled(config, subcategory):
            continue

        alternatives = fetch_alternatives(match)

        label = match["shortMessage"]
        if label == "":
            try:
                label = match["rule"]["category"]["name"]
            except KeyError:
                pass

        if not subcategory.endswith("abbreviation") and not subcategory.endswith(
            "anglicism"
        ):
            explanation = match["message"]
        else:
            explanation = None

        list_results.append(
            ResultOut.factory(
                version,
                config,
                lang,
                text,
                full_text,
                offsets,
                subcategory,
                start,
                end,
                alternatives,
                label,
                explanation,
            )
        )

    return list_results


async def fetch_json_from_language_service(
    lang, url, payload, is_get=False
):  # pragma: no cover
    url = settings.language_endpoint_urls[lang] + url
    headers = {"content-type": "application/json"}
    name = "language endpoint " + lang

    if is_get:
        return await fetch_json_get(
            url, payload, headers, name, settings.languagetool_verify_ssl
        )

    return await fetch_json_post(
        url, payload, headers, name, settings.languagetool_verify_ssl
    )


async def handle_response(r, name, json=True):
    try:
        if r.status != 200:  # pragma: no cover
            result = await r.text()
            logging.error(result)

            raise Exception(result)

        if json:
            return await r.json()

        return await r.text()
    except aiohttp.ClientError as err:  # pragma: no cover
        result = "Problem communicating with " + name
        if r.status >= 500:
            try:
                response = await r.text()
                result += ": " + response
            except aiohttp.ClientError as err:
                result += ": " + str(err)
        else:
            result += ": " + str(err)

        logging.error(result)

    return result


async def fetch_json_get(url, payload, headers, name, ssl=True, json=True):
    if ssl:
        async with ssl_session.get(url, params=payload, headers=headers) as r:
            return await handle_response(r, name, json)

    async with session.get(url, params=payload, headers=headers) as r:
        return await handle_response(r, name, json)


async def fetch_json_post(url, payload, headers, name, ssl=True, json=True):
    if ssl:
        async with ssl_session.post(url, data=payload, headers=headers) as r:
            return await handle_response(r, name, json)

    async with session.post(url, data=payload, headers=headers) as r:
        return await handle_response(r, name, json)


async def apply_languagetool_rules(
    version: float, config: Config, lang: Language, text: str, offsets
):
    if settings.languagetool_api == "":
        return []

    payload = {
        "text": text,
        "language": lang.locale,
        "disabledCategories": ["GENDER_NEUTRALITY", "COLLOQUIALISMS"],
        "enabledCategories": [],
    }

    if is_sub_category_enabled(config, "advanced_plain_language"):
        if payload["language"] == "de-DE":
            payload["language"] += "-x-simple-language"

        payload["enabledCategories"].append("PLAIN_ENGLISH")
    else:
        payload["disabledCategories"].append("PLAIN_ENGLISH")

    if config.primary_language is not None:
        payload["motherTongue"] = config.primary_language

    if is_sub_category_enabled(config, "orthography"):
        if "casing" in config.disabled_categories:
            payload["disabledCategories"].append("CASING")

        if "style" in config.disabled_categories:
            payload["disabledCategories"] += lt_style_categories
    elif is_sub_category_enabled(config, "style"):
        payload["enabledCategories"] += lt_style_categories
    else:
        return []

    result = await fetch_json_post(
        settings.languagetool_api + "/check",
        payload,
        {},
        "LanguageTool",
        settings.languagetool_verify_ssl,
    )

    if not isinstance(result, dict):
        return []

    return languagetool_matches(version, config, lang, text, offsets, result)


def utf16len(c):
    """Returns the length of the single character 'c'
    in UTF-16 code units."""
    return 1 if ord(c) < 65536 else 2


def fetch_tokens(lang, text: str):
    return model[lang](text.rstrip().replace("\n", " "))


def utf16_offsets(text):
    utf16offset = 0

    offsets = {
        "chars": [],
        "utf16_chars": [],
    }

    counter = 0
    for char in [*text]:
        offsets["chars"].append(counter + utf16offset)
        offsets["utf16_chars"].append(counter - utf16offset)

        counter += 1

        if utf16len(char) > 1:
            utf16offset += 1

    offsets["chars"].append(counter + utf16offset)
    offsets["utf16_chars"].append(counter - utf16offset)

    return offsets if utf16offset else False


# matcher to false positives
def is_false_positive_match(false_positive_matcher, tokens, token):
    if false_positive_matcher is None:
        return False

    for match_id, start, end in false_positive_matcher:
        span_false = tokens[start:end]
        if token.idx in range(span_false.start_char, span_false.end_char):
            return True

    return False


# create false positives patterns based on false positives column
def false_pattern_match(lang, tokens):
    matcher = Matcher(model[lang].vocab)

    for false_positive in rules[lang]["pattern_false_positives"]:
        matcher.add("FalsePositivesList", false_positive)

    return matcher(tokens)


def fetch_false_positive_matcher(lang, tokens):
    # create false positives list
    phrase_false_positive_matcher = fetch_matches(lang, tokens, rules[lang]["list_false_column"])
    word_false_positive_matcher = false_pattern_match(lang, tokens)
    return list(set(phrase_false_positive_matcher + word_false_positive_matcher))


def fetch_matches(lang, tokens, phrases):
    # Phrase matcher part to handle False positives with two words and special symbols
    matcher = PhraseMatcher(model[lang].vocab, attr="LOWER")

    # Only run model.make_doc to speed things up
    patterns = [model[lang].make_doc(text) for text in phrases]
    matcher.add("TerminologyList", patterns)
    return matcher(tokens)


async def fetch_language_results(  # pragma: no cover
    version: float,
    client: str,
    config: Config,
    configs: dict,
    lang: Language,
    text: str,
):
    if lang.lang == "de":
        url = "/german"
        payload = GermanLanguageRequest(
            version=version,
            client=client,
            config=config,
            configs=configs,
            locale=lang.locale,
            text=text,
        )
    else:
        url = "/english"
        payload = EnglishLanguageRequest(
            version=version,
            client=client,
            config=config,
            configs=configs,
            locale=lang.locale,
            text=text,
        )

    result = await fetch_json_from_language_service(lang.lang, url, payload.json())
    if result is None:
        return []

    return parse_obj_as(List[ResultOut], result)


async def apply_language_rules(
    version: float,
    client: str,
    config: Config,
    configs: dict,
    lang: Language,
    text: str,
):
    list_results = []

    client = VersionString(client)

    if settings.language_endpoint_urls[lang.lang]:
        list_results += await fetch_language_results(
            version,
            client,
            config,
            configs,
            lang,
            text,
        )
    elif lang.lang == "de":
        list_results += await german_rules(version, client, config, configs, lang, text)
    elif lang.lang == "en":
        list_results += await english_rules(
            version, client, config, configs, lang, text
        )

    return apply_false_positives(list_results, configs)


def apply_term_replacements(
    version: float,
    config: Config,
    lang: Language,
    text: str,
    tokens,
    offsets,
    configs: dict,
):
    if "term_replacements" not in configs:
        return []

    term_replacements_case_insensitive = {}
    term_replacements_case_sensitive = {}

    term_replacements_lemma = {
        "Lemma": [],
        "Word_Type": [],
        "Alt_split": [],
        "Primary_subcategory": [],
        "Explanation": [],
    }

    for term in configs["term_replacements"]:
        term_replacement = configs["term_replacements"][term]

        if term[-3:] == "|en" or term[-3:] == "|de":
            if term[-2:] != lang.lang:
                continue

            term = term[0:-3]
        # BC code
        elif (
            "lang" in term_replacement
            and term_replacement["lang"] != lang.lang
            and term_replacement["lang"] is not None
        ):
            continue

        if "word_type" in term_replacement:
            word_type = term_replacement["word_type"]
        else:
            word_type = "-"

        if word_type == "-":
            regexp = r"(?i)(\b" + term + r"\b)"
            term_replacements_case_insensitive[regexp] = term_replacement
        elif word_type == "=":
            regexp = r"(\b" + term + r"\b)"
            term_replacements_case_sensitive[regexp] = term_replacement
        else:
            term_replacements_lemma["Lemma"].append(term)
            term_replacements_lemma["Word_Type"].append(word_type)
            term_replacements_lemma["Primary_subcategory"].append("corporate_rules")
            term_replacements_lemma["Alt_split"].append(
                term_replacement["alternatives"]
            )
            term_replacements_lemma["Explanation"].append(
                term_replacement["explanation"]
            )

    list_result = []

    if len(term_replacements_case_insensitive):
        list_result += regex_matches(
            version,
            config,
            lang,
            text,
            offsets,
            term_replacements_case_insensitive,
            "corporate_rules",
        )

    if len(term_replacements_case_sensitive):
        list_result += regex_matches(
            version,
            config,
            lang,
            text,
            offsets,
            term_replacements_case_sensitive,
            "corporate_rules",
        )

    if len(term_replacements_lemma):
        term_replacements = list(
            zip(
                term_replacements_lemma["Lemma"],
                term_replacements_lemma["Word_Type"],
                term_replacements_lemma["Primary_subcategory"],
                term_replacements_lemma["Alt_split"],
                term_replacements_lemma["Explanation"],
            )
        )

        list_result += rules_based_words_phrase_matcher(
            version,
            config,
            lang,
            text,
            tokens,
            offsets,
            term_replacements,
        )

    return list_result


def apply_false_positives(
    list_results: List,
    configs: dict,
):
    if len(list_results) == 0:
        return list_results

    false_positives = []
    if "false_positives" in configs:
        false_positives = configs["false_positives"]

    if "term_replacements" in configs:
        for term_replacement in configs["term_replacements"]:
            false_positives.append(
                configs["term_replacements"][term_replacement]["alternatives"][0]
            )

    if len(false_positives):
        for result in list_results:
            if result.text in false_positives:
                list_results.remove(result)

    return list_results


def is_sub_category_enabled(config: Config, subcategory: str):
    if subcategory in config.disabled_categories:
        return False

    category_data = get_category(subcategory)
    if category_data is None:
        return False

    if (
        "category" in category_data
        and category_data["category"] in config.disabled_categories
    ):
        return False

    return True


async def context_false_positives(lang, tokens, list_results):
    if (
        len(rules[lang]["context_check"]) == 0
        or not settings.context_checker_url
        or not settings.context_checker_api_key
    ):
        return list_results

    sentences = {}
    sentences_to_check = {}
    for i in range(len(list_results)):
        result = list_results[i]
        words = result.text.lower().split()
        if not len(words):
            continue

        # a fossil => fossil
        if words[-1] in rules[lang]["context_check"]:
            if sentences == {}:
                for sentence in tokens.sents:
                    sentences[sentence.end_char] = sentence.text

            sentence = None
            for end_char in sentences:
                if result.end <= end_char:
                    sentence = sentences[end_char]
                    break

            if sentence is None:
                continue

            if sentence in sentences_to_check:
                sentences_to_check[sentence].append(i)
            else:
                sentences_to_check[sentence] = [i]

    if sentences_to_check == {}:
        return list_results

    sentences = list(sentences_to_check.keys())

    headers = {
        "Content-Type": "application/json",
        "Authorization": ("Bearer " + settings.context_checker_api_key),
    }

    payload = {
        "data": sentences,
    }

    context_results = await fetch_json_post(
        settings.context_checker_url, json.dumps(payload), headers, "context checker"
    )

    keys_to_remove = []
    for i in range(len(sentences)):
        sentence = sentences[i]
        if context_results[i] == "1":
            continue

        for result_key in sentences_to_check[sentence]:
            if result_key in keys_to_remove:
                continue

            keys_to_remove.append(result_key)

    # ensure we remove from the end so that the list indexes remain the same
    keys_to_remove.sort(reverse=True)
    for key_to_remove in keys_to_remove:
        list_results.pop(key_to_remove)

    return list_results


async def german_rules(
    version: float,
    client: str,
    config: Config,
    configs: dict,
    lang: Language,
    text: str,
):
    offsets = utf16_offsets(text)

    list_full = await apply_languagetool_rules(version, config, lang, text, offsets)

    tokens = fetch_tokens(lang.lang, text)

    list_full += detect_non_inclusive_emoji(
        version,
        client,
        config,
        lang,
        text,
        tokens,
        offsets,
    )

    if is_sub_category_enabled(config, "abbreviation"):
        list_full += literal_match(
            version,
            config,
            lang,
            text,
            tokens,
            offsets,
            rules["de"]["df_abbreviation"],
            rules["de"]["abbreviation"],
            True,
        )

    list_full += rules_based_words_phrase_matcher(
        version,
        config,
        lang,
        text,
        tokens,
        offsets,
        rules["de"]["open_disc_words_data"],
        rules["de"]["open_disc_sentences_data"],
        rules["de"]["df_open_dis_sentence"],
    )

    list_full += rules_based_words_phrase_matcher(
        version,
        config,
        lang,
        text,
        tokens,
        offsets,
        rules["de"]["gender_words_data_no_noun"],
        rules["de"]["gender_sentences_data"],
        rules["de"]["df_gendered_sentences"],
    ) + gendered_denom_analysis_de(
        version,
        config,
        lang,
        text,
        tokens,
        offsets,
        rules["de"]["gender_words_data"],
        rules["de"]["false_positives"].gender,
    )

    if is_sub_category_enabled(config, "gender_specific_abbreviation"):
        list_full += regex_matches(
            version,
            config,
            lang,
            text,
            offsets,
            rules["m_f_regexes"],
            "gender_specific_abbreviation",
        )

    if ResultOut.genderedRolesFormatInclusive(config.gendered_roles_format):
        subcategory = "advanced_gendered_denominations_ending"

        regexes = {}
        for ending, regex in config._gendereddenom_ending.items():
            if (
                config.german_gender_ending == ending
                # avoid issues with LinkedIn
                or ending == GermanGenderEndingType.CAPITAL_LETTER
            ):
                continue

            regexes[regex] = config.german_gender_ending[0:-2]

        list_full += regex_matches(
            version,
            config,
            lang,
            text,
            offsets,
            regexes,
            subcategory,
        )

    list_full += ub_words_phrase_matcher_de(
        version,
        config,
        lang,
        text,
        tokens,
        offsets,
        rules["de"]["bias_words_data_no_plur"],
        rules["de"]["bias_sentences_data"],
        rules["de"]["df_ub_sentences"],
    )

    list_full += word_noun(
        version,
        config,
        lang,
        text,
        tokens,
        offsets,
        rules["de"]["bias_words_data_noun"],
    )

    if is_sub_category_enabled(config, "communal"):
        list_full += rules_based_words_phrase_matcher(
            version,
            config,
            lang,
            text,
            tokens,
            offsets,
            rules["de"]["df_communal_words"],
            None,
            [],
            [],
            "communal",
        )

    if is_sub_category_enabled(config, "d_and_i"):
        list_full += rules_based_words_phrase_matcher(
            version,
            config,
            lang,
            text,
            tokens,
            offsets,
            rules["de"]["df_d_and_i_words"],
            None,
            rules["de"]["df_terms_d_and_i_words"],
            [],
            "d_and_i",
        )

        subcategory = "d_and_i"
        regexes = {config._gendereddenom_ending[config.german_gender_ending]: None}

        regexes.update(rules["d_f_m_regexes"])

        list_full += regex_matches(
            version, config, lang, text, offsets, regexes, subcategory
        )

    list_full += style_word_analysis_de(
        version,
        config,
        lang,
        text,
        tokens,
        offsets,
        rules["de"]["terms_style"],
        rules["de"]["style_words_data"],
        rules["de"]["style_sentences_data"],
        rules["de"]["false_positives"].style,
    )

    list_full += detect_lower_cased_hashtags(
        version,
        config,
        lang,
        text,
        offsets,
    )

    list_full += apply_term_replacements(
        version, config, lang, text, tokens, offsets, configs
    )

    return await context_false_positives(lang.lang, tokens, list_full)


async def english_rules(
    version: float,
    client: str,
    config: Config,
    configs: dict,
    lang: Language,
    text: str,
):
    offsets = utf16_offsets(text)

    list_full = await apply_languagetool_rules(version, config, lang, text, offsets)

    tokens = fetch_tokens(lang.lang, text)

    list_full += detect_non_inclusive_emoji(
        version,
        client,
        config,
        lang,
        text,
        tokens,
        offsets,
    )

    words_data_en = defaultdict(list)
    gendered_words_data_en = defaultdict(list)
    sentences_data_en = defaultdict(list)
    false_positive_matcher = fetch_false_positive_matcher(lang.lang, tokens)

    words_data_en["od"] = rules[lang.locale]["open_disc_words_data"]
    words_data_en["ge"] = rules[lang.locale]["gender_words_data"]
    words_data_en["ge-singular-they"] = rules[lang.locale][
        "bias_singular_they_alternatives"
    ]
    words_data_en["style"] = rules[lang.locale]["style_words_data"]
    words_data_en["bias"] = rules[lang.locale]["bias_words_data"]
    words_data_en["homonym"] = rules[lang.locale]["homonyms_word"]
    words_data_en["abbr"] = rules[lang.locale]["abbreviation"]

    inclusive_words_data_en = rules[lang.locale]["inclusive_words_data"]
    gendered_words_data_en["gendered"] = rules[lang.locale]["gender_noun_words_data"]
    gendered_words_data_en["bias"] = rules[lang.locale]["gender_bias_words_data"]
    gendered_words_data_en["style"] = rules[lang.locale]["style_noun_words_data"]
    inclusive_sentences_data_en = rules[lang.locale]["inclusive_sentences_data"]
    sentences_data_en["od"] = rules[lang.locale]["open_dis_sentences"]
    sentences_data_en["ge"] = rules[lang.locale]["gender_sentences_data"]
    sentences_data_en["style"] = rules[lang.locale]["style_sentences_data"]
    sentences_data_en["bias"] = rules[lang.locale]["bias_sentences_data"]

    list_full += homonyms_en(
        version,
        config,
        lang,
        text,
        tokens,
        offsets,
        false_positive_matcher,
        words_data_en["homonym"],
    )

    if is_sub_category_enabled(config, "abbreviation"):
        list_full += literal_match(
            version,
            config,
            lang,
            text,
            tokens,
            offsets,
            rules[lang.locale]["df_abbreviation"],
            words_data_en["abbr"],
            True,
        )

    list_full += rules_based_words_phrase_matcher(
        version,
        config,
        lang,
        text,
        tokens,
        offsets,
        words_data_en["od"],
        sentences_data_en["od"],
        rules[lang.locale]["df_open_dis_sentence"],
        false_positive_matcher,
    )

    list_full += rules_based_words_phrase_matcher(
        version,
        config,
        lang,
        text,
        tokens,
        offsets,
        words_data_en["ge"],
        sentences_data_en["ge"],
        rules[lang.locale]["df_gendered_sentence"],
        false_positive_matcher,
    )

    if is_sub_category_enabled(config, "advanced_binary_pronouns"):
        list_full += rules_based_words_phrase_matcher(
            version,
            config,
            lang,
            text,
            tokens,
            offsets,
            words_data_en["ge-singular-they"],
            [],
            [],
            false_positive_matcher,
            None,
            True,
        )

    list_full += word_noun(
        version,
        config,
        lang,
        text,
        tokens,
        offsets,
        gendered_words_data_en["gendered"],
        false_positive_matcher,
    )

    if is_sub_category_enabled(config, "advanced_binary_pronouns"):
        list_full += regex_matches(
            version,
            config,
            lang,
            text,
            offsets,
            rules["m_f_regexes"],
            "gender_specific_abbreviation",
        )

    if is_sub_category_enabled(config, "d_and_i"):
        subcategory = "d_and_i"

        list_full += regex_matches(
            version,
            config,
            lang,
            text,
            offsets,
            rules["d_f_m_regexes"],
            subcategory,
        )

    list_full += rules_based_words_phrase_matcher(
        version,
        config,
        lang,
        text,
        tokens,
        offsets,
        inclusive_words_data_en,
        inclusive_sentences_data_en,
        rules[lang.locale]["df_inclusive_sentence"],
        false_positive_matcher,
    )

    list_full += rules_based_words_phrase_matcher(
        version,
        config,
        lang,
        text,
        tokens,
        offsets,
        words_data_en["style"],
        sentences_data_en["style"],
        rules[lang.locale]["df_style_sentence"],
        false_positive_matcher,
    )

    list_full += word_noun(
        version,
        config,
        lang,
        text,
        tokens,
        offsets,
        gendered_words_data_en["style"],
        false_positive_matcher,
    )

    list_full += detect_lower_cased_hashtags(
        version,
        config,
        lang,
        text,
        offsets,
    )

    list_full += rules_based_words_phrase_matcher(
        version,
        config,
        lang,
        text,
        tokens,
        offsets,
        words_data_en["bias"],
        sentences_data_en["bias"],
        rules[lang.locale]["df_ub_sentence"],
        false_positive_matcher,
    )

    list_full += word_noun(
        version,
        config,
        lang,
        text,
        tokens,
        offsets,
        gendered_words_data_en["bias"],
        false_positive_matcher,
    )

    list_full += apply_term_replacements(
        version, config, lang, text, tokens, offsets, configs
    )

    return await context_false_positives(lang.lang, tokens, list_full)


def parse_word_types(word_types, lower_case=True):
    lemmatize = True

    if word_types is None:
        return [], lower_case, lemmatize

    if word_types[0] == "~":
        # exact match
        lower_case = True
        lemmatize = False
        word_types = word_types[1:]
    if word_types[0] == "=":
        # exact match
        lower_case = False
        lemmatize = False
        word_types = word_types[1:]
    elif word_types[0] == "-":
        # force lower case off
        lower_case = False
        lemmatize = True
        word_types = word_types[1:]

    word_types = word_types.split("+")
    if word_types == [""]:
        word_types = []

    return word_types, lower_case, lemmatize


def is_word_match(
    lang,
    token,
    tokens,
    word,
    word_types,
    false_positive_matcher=None,
    lower_case=True,
    postfix=False,
):
    word_types, lower_case, lemmatize = parse_word_types(word_types, lower_case)

    if lemmatize:
        token_word = token.lemma_
    else:
        token_word = token.text

    if lower_case and (lang == "en" or "s" not in word_types):
        token_word = token_word.lower()

    if token_word == word:
        postfix = False
    elif not postfix or not token_word.endswith(word.lower()):
        return False

    if not check_word_types(lang, token, word_types, True):
        return False

    match = is_false_positive_match(false_positive_matcher, tokens, token) == False
    if match and postfix:
        return "postfix"

    return match


"""Function to catch the words related to False Positive in the user query"""


def is_false_positive(word, false_positive):
    for item in false_positive:
        if word == item:
            return True

    return False


"""Function to change adjectives to -en form in alternatives"""


def fetch_word_types(lang, token, word_types=[], single_word=None):
    # https://machinelearningknowledge.ai/tutorial-on-spacy-part-of-speech-pos-tagging/
    # https://github.com/explosion/spaCy/blob/master/spacy/glossary.py

    if "adv" in word_types and token.pos_ == "ADV":
        return ["adv"]

    if token.pos_ == "VERB":
        if lang == "de" and "a" in word_types:
            return ["a"]

        return ["v"]

    if token.pos_ == "NOUN" or token.pos_ == "PRON":
        return ["s"]

    adj_tags = {
        "AFX",
        "ADJA",
        "ADJD",
        "ADV",
        "ADJ",
        "JJ",
        "JJR",
        "JJS",
        "PDT",
        "PRP$",
        "VVPP",
        "VAPP",
        "VMPP",
        "WP$",
        "WDT",
    }
    if token.tag_ in adj_tags or token.pos_ in adj_tags:
        return ["a"]

    if token.tag_ == "NN":
        return ["s"]

    if token.pos_ == "PROPN" and single_word is not None and len(word_types):
        return word_types[0:1]

    return []


def check_word_types(lang, token, word_types=[], single_word=None):
    if word_types == []:
        return True

    return word_types_overlap(
        fetch_word_types(lang, token, word_types, single_word), word_types
    )


def find_common_prefix(a_text, a_lemma):
    prefix = a_text.lower()
    while a_lemma[: len(prefix)] != prefix and prefix:
        prefix = prefix[: len(prefix) - 1]
        if not prefix:
            break

    return prefix


def add_declension_german(text, a_text, a_lemma, injected_string=""):
    prefix = find_common_prefix(a_text, a_lemma)
    ending = a_text[len(prefix) :]
    if injected_string and ending[0 : len(injected_string)] == injected_string:
        a_text = prefix + a_text[len(prefix) + len(injected_string) :]
        a_text = a_text.strip()
        prefix = find_common_prefix(a_text, a_lemma)
        ending = a_text[len(prefix) :]

    if a_lemma == "beste":
        ending = "ste" + ending
        if text[-1] == "t" or text[-1] == "s":
            text += "e"
    else:
        remove = a_lemma[len(prefix) :]
        if remove:
            text = text[0 : -len(remove)]

    if ending != "" and len(text) > 2:
        if text[-2:] == "em":
            return text

        if text[-1] == "t" and ending == "t":
            text += "e"
        elif text[-1] == "s":
            text += "s"
        elif text[-1] == "e" and ending[0] == "e":
            text = text[0:-1]

    return text + ending


def word_types_overlap(a_word_types, b_word_types):
    return not set(a_word_types).isdisjoint(b_word_types)


def determine_genus_from_ending(word, german_genus_endings):
    for genus in german_genus_endings:
        for ending in german_genus_endings[genus]:
            if word.endswith(ending):
                return {"genus": genus}

    return None


def german_noun_lookup(word):
    if word in rules["de"]["gender_neutral_nouns"]:
        return rules["de"]["gender_neutral_nouns"][word]

    result = rules["de"]["german_nouns"][word]
    if not len(result):
        return None

    result = result[0]
    if "flexion" in result:
        for flexion in list(result["flexion"].keys()):
            if "1" in flexion:
                result["flexion"][flexion.replace(" 1", "")] = result["flexion"][
                    flexion
                ]

    if "genus" in result:
        return result

    if "genus 1" in result:
        result["genus"] = result["genus 1"]

        return result

    if word[-5:].lower() == "leute":
        result["is_plural"] = True
        result["genus"] = "f"

        return result

    genus_result = determine_genus_from_ending(
        word, rules["de"]["primary_german_genus_endings"]
    )
    if genus_result == None or "genus" not in genus_result:
        genus_result = determine_genus_from_ending(
            word, rules["de"]["secondary_german_genus_endings"]
        )
        if genus_result == None or "genus" not in genus_result:
            logging.error(
                "Unable to determine german noun genus for: %s",
                word,
            )

            return None

    result["genus"] = genus_result["genus"]

    return result


def german_noun_analysis(word, genus_only=False):
    if "..." in word:
        return None

    result = german_noun_lookup(word)
    if result != None:
        return result

    if genus_only:
        result = determine_genus_from_ending(
            word, rules["de"]["primary_german_genus_endings"]
        )

        if result != None:
            return result

    # skip the first 2 letters
    i = 2

    # skip the last 2 letters
    while i < len(word) - 2:
        partial_word = word[i:]

        result = german_noun_lookup(partial_word.capitalize())
        if result == None:
            i += 1
            continue

        result["lemma"] = word
        if genus_only:
            if "flexion" in result:
                del result["flexion"]
        else:
            word_prefix = word[0:i]
            for flexion in result["flexion"]:
                result["flexion"][flexion] = (
                    word_prefix + result["flexion"][flexion].lower()
                )

        logging.error(
            "Determined german noun data for '%s' as '%s'", word, partial_word
        )

        return result

    logging.error(
        "Unable to determine german noun data for: %s",
        word,
    )

    if genus_only:
        result = determine_genus_from_ending(
            word, rules["de"]["secondary_german_genus_endings"]
        )

    return result


def fetch_flexion(token):
    if token.morph.get("Case") == ["Dat"]:
        flexion = "dativ"
    elif token.morph.get("Case") == ["Gen"]:
        flexion = "genitiv"
    elif token.morph.get("Case") == ["Nom"]:
        flexion = "nominativ"
    elif token.morph.get("Case") == ["Acc"]:
        flexion = "akkusativ"
    else:
        return None

    if token.morph.get("Number") == ["Sing"]:
        flexion += " singular"
    else:
        flexion += " plural"

    return flexion


def align_noun_form(lang, a_text, a_token, b_token):
    b_text = b_token.text

    if a_token.morph.get("Number") == b_token.morph.get("Number") or b_text == "they":
        return b_text

    if lang == "de":
        a_word = german_noun_analysis(a_text)
        if a_word is None:
            return b_text

        b_word = german_noun_analysis(b_text)
        if b_word is None:
            return b_text

        flexion = fetch_flexion(a_token)
        if flexion is None:
            return b_text

        if flexion in b_word["flexion"]:
            return b_word["flexion"][flexion]

        key = flexion + " stark"
        if key in b_word["flexion"]:
            return b_word["flexion"][key]

        return b_text

    is_singular = is_token_singular(lang, b_token)

    if is_singular == True or (is_singular is None and is_token_plural(lang, a_token)):
        return Noun(b_text).plural()

    if is_singular == False:
        return b_text

    return Noun(b_text).singular()


def align_adjective_form(lang, a_text, a_token, b_token):
    if lang == "de":
        return add_declension_german(b_token.text, a_text, a_token.lemma_)

    b_text = b_token.lemma_
    a_adjective = Adjective(a_text)
    b_adjective = Adjective(b_text)

    if a_adjective.is_singular():
        b_text = b_adjective.singular()
        b_adjective = Adjective(b_text)
    elif a_adjective.is_plural():
        b_text = b_adjective.plural()
        b_adjective = Adjective(b_text)

    a_adjective_lemma = Adjective(a_token.lemma_)
    if a_adjective_lemma.comparative() == a_text:
        b_text = b_adjective.comparative()
    elif a_adjective_lemma.superlative() == a_text:
        b_text = b_adjective.superlative()

    return b_text


def german_verb_splittable(word):  # pragma: no cover
    logging.error(
        "Guessing how to split: %s",
        word,
    )

    prefixes = (
        "ge",
        "er",
        "be",
        "ent",
        "emp",
        "ver",
        "zer",
        "hinter",
        "miss",
        "ob",
    )

    if word.startswith(prefixes):
        return False

    prefixes = [
        "ab",
        "an",
        "auf",
        "aus",
        "bei",
        "ein",
        "mit",
        "nach",
        "weg",
        "zu",
        "her",
        "nach",
        "überein",
        "umher",
    ]
    for prefix in prefixes:
        if word.startswith(prefix):
            return prefix

    for prefix in rules["de"]["splittable_words"]:
        if word.startswith(prefix):
            if word in rules["de"]["splittable_words"][prefix]:
                return prefix

            return False

    # detect "adjective + verb" case
    i = 2  # skip the first 2 letters
    while i < len(word) - 2:  # skip the last 2 letters
        prefix = word[0:i]
        partial_word = word[i:]
        if partial_word in rules["de"]["verbs"]:
            tokens = fetch_tokens("de", prefix + " " + partial_word)
            if "a" in fetch_word_types("de", tokens[0]) and "v" in fetch_word_types(
                "de", tokens[1]
            ):
                return prefix

        i += 1

    return False


def fetch_verb_form(token):
    if token.morph.get("Case") == ["Dat"]:
        flexion = "dativ"
    elif token.morph.get("Case") == ["Gen"]:
        flexion = "genitiv"
    elif token.morph.get("Case") == ["Nom"]:
        flexion = "nominativ"
    elif token.morph.get("Case") == ["Acc"]:
        flexion = "akkusativ"
    else:
        return None

    if token.morph.get("Number") == ["Sing"]:
        flexion += " singular"
    else:
        flexion += " plural"

    return flexion


def align_verb_form(lang, a_text, a_token, b_token):
    if lang == "de":
        b_text = b_token.text
        injected_string = ""

        # check if "zu" was stripped from the word in the lemma
        if a_text.count("zu") > a_token.lemma_.count("zu"):
            if b_text in rules["de"]["verbs"]:
                return rules["de"]["verbs"][b_text]["infinitiv_zu"]

            # pragma: no cover
            prefix = german_verb_splittable(b_text)
            if prefix:
                b_text = prefix + "zu" + b_text[len(prefix) :]
            else:
                b_text = "zu " + b_text

            injected_string = "zu"
        # check if "ge" was stripped from the word in the lemma
        elif a_token.text.count("ge") > a_token.lemma_.count("ge"):
            if b_text in rules["de"]["verbs"]:
                return rules["de"]["verbs"][b_text]["past_participle"]

            # pragma: no cover
            prefix = german_verb_splittable(b_text)
            if prefix:
                b_text = prefix + "ge" + b_text[len(prefix) :]

            injected_string = "ge"
        elif b_text in rules["de"]["verbs"]:
            morph = a_token.morph.to_dict()
            if (
                "Number" in morph
                and morph["Number"] == "Sing"
                and "Person" in morph
                and morph["Person"] == "1"
            ):
                return rules["de"]["verbs"][b_text]["present_ich"]

        return add_declension_german(b_text, a_text, a_token.lemma_, injected_string)

    b_text = b_token.lemma_
    a_verb = Verb(a_text)
    b_verb = Verb(b_text)

    if a_verb.is_singular():
        b_text = b_verb.singular()
        b_verb = Verb(b_text)
    elif a_verb.is_plural():
        b_text = b_verb.plural()
        b_verb = Verb(b_text)

    if a_verb.is_past():
        b_text = b_verb.past()
    elif a_verb.is_pres_part():
        b_text = b_verb.pres_part()
    elif a_verb.is_past_part():
        b_text = b_verb.past_part()

    return b_text


def alternative_declension(lang, text, token, word_types, alternative):
    (
        parsed_alternative,
        alternative_context,
        remove,
    ) = ResultOut.parse_alternative(alternative)

    if alternative_context is None:
        alternative_context = ""
    else:
        alternative_context = " ---" + alternative_context

    if (
        not parsed_alternative
        or remove
        or ResultOut.isInspirationAlternative(parsed_alternative)
    ):
        return alternative

    if parsed_alternative.count(" ") > 5:
        return alternative

    new_alternative = ""
    previous = False
    is_plural_alternative = False
    first_alternative_word_types = False
    alternative_tokens = fetch_tokens(lang, parsed_alternative)
    for i in reversed(range(len(alternative_tokens))):
        alternative_token = alternative_tokens[i]
        alternative_text = alternative_token.text
        if alternative_text != "," and token_is_conjunction(alternative_token):
            previous = False
        else:
            if len(alternative_tokens) == 1:
                # in this case we just assume it is the same to avoid issues with word type detection
                alternative_word_types = word_types
            else:
                alternative_word_types = fetch_word_types(
                    lang, alternative_token, word_types, False
                )

            if first_alternative_word_types == False:
                first_alternative_word_types = alternative_word_types

            if previous == False:
                if "v" in word_types and lang == "en" and i == 0:
                    previous = True
                    alternative_text = align_verb_form(
                        lang, text, token, alternative_token
                    )
                elif "s" in word_types and "s" in alternative_word_types:
                    if is_token_plural(lang, alternative_token):
                        is_plural_alternative = True

                    previous = True
                    alternative_text = align_noun_form(
                        lang, text, token, alternative_token
                    )
                elif word_types_overlap(word_types, alternative_word_types):
                    if "a" in alternative_word_types:
                        previous = True
                        alternative_text = align_adjective_form(
                            lang, text, token, alternative_token
                        )
                    elif "v" in alternative_word_types:
                        previous = True
                        alternative_text = align_verb_form(
                            lang, text, token, alternative_token
                        )

        new_alternative = (
            alternative_text + alternative_token.whitespace_ + new_alternative
        )

    if lang == "en" and first_alternative_word_types:
        if (
            is_plural_alternative == False
            and (text.lower().startswith("a ") or text.lower().startswith("an "))
            and not new_alternative.startswith(rules["en"]["a_not_startswith"])
            and not new_alternative.endswith(rules["en"]["uncountables"])
        ):
            if new_alternative[0].lower() in ["a", "e", "i", "o", "u"]:
                new_alternative = "an " + new_alternative
            else:
                new_alternative = "a " + new_alternative

    return new_alternative + alternative_context


def alternatives_declension(lang, token, alternatives, prev_token):
    text = token.text
    start = token.idx

    word_types = fetch_word_types(lang, token)
    if lang == "de":
        if "v" in word_types and prev_token and prev_token.text == "zu":
            text = "zu " + text
            start = prev_token.idx
    elif lang == "en" and (
        prev_token
        and (prev_token.text.lower() == "a" or prev_token.text.lower() == "an")
    ):
        text = prev_token.text + " " + text
        start = prev_token.idx

    if word_types == [] or (
        text.lower() == token.lemma_.lower() and token.lemma_ != "beste"
    ):
        return text, start, alternatives

    return (
        text,
        start,
        [
            alternative_declension(lang, text, token, word_types, alternative).strip()
            for alternative in alternatives
        ],
    )


def plural_alternatives(
    token,
    alternative_plur,
    second_subcategory,
):
    return [
        item for item in alternative_plur if item != token.text.lower()
    ], second_subcategory


def match_binary_inclusive_gendered_denom_analysis_de(
    version: float, config: Config, false_positives, full_text, tokens, i, subcategory
):
    tokens_length = len(tokens)
    token = tokens[i]
    text = token.text
    start = token.idx

    if tokens_length <= 2:
        return text, start, subcategory

    is_binary = ResultOut.genderedRolesFormatBinary(config.gendered_roles_format)

    for false_positive in false_positives:
        if "/" in false_positive:
            # "foo/bar" case
            split_char = "/"
        else:
            # "foo und bar" case
            split_char = " und "

        false_positive_words = false_positive.lower().split(split_char)

        if (
            tokens_length > i + 3
            and tokens[i + 1].text == split_char.strip()
            and tokens[i + 2].text.lower().endswith(false_positive_words[1])
        ):
            if "frau" in text.lower():
                return None, None, None

            # [token]/foo - [token] und foo
            new_i = i
        elif (
            i >= 2
            and tokens[i - 1].text == split_char.strip()
            and (
                tokens[i - 2].text.lower().endswith(false_positive_words[0])
                or tokens[i - 2].text.lower().endswith(false_positive_words[0] + "n")
            )
        ):
            # foo/[token] - foo und [token] - foo und [token]n
            new_i = i - 2
        else:
            continue

        if ResultOut.genderedRolesFormatBinary(config.gendered_roles_format):
            return None, None, None

        start = tokens[new_i].idx
        text = full_text[start : (tokens[new_i + 2].idx + len(tokens[new_i + 2].text))]

        subcategory = (
            "function" if "mann" in text.lower() else "gendered_denominations_ending"
        )

        return text, start, subcategory

    return text, start, subcategory


def fetch_article_for_flexion(flexion, word, article_text):
    if flexion is None:
        return None, None, None, None

    for form, masculine, feminine, neuter, plural, alternative in rules["de"][
        "articles"
    ]:
        if form not in flexion:
            continue

        article_to_check = None
        if word["genus"] == "m":
            article_to_check = masculine
        elif word["genus"] == "f":
            article_to_check = feminine
        elif word["genus"] == "n":
            article_to_check = neuter

        if article_text == article_to_check:
            return masculine, feminine, neuter, alternative

    return None, None, None, None


def fetch_alternatives_with_article(tokens, i, alternatives):
    token = tokens[i]
    text = token.text
    word = german_noun_analysis(text)
    if word is None:
        return None

    article_text = tokens[i - 1].text.lower()

    (
        match_masculine,
        match_feminine,
        match_neuter,
        match_alternative,
    ) = fetch_article_for_flexion(fetch_flexion(token), word, article_text)
    if match_alternative is None:
        return None

    alternatives_with_article = []
    for alternative in alternatives:
        if "~" in alternative:
            if match_alternative:
                article_alternative = match_alternative
            else:
                article_alternative = article_text
        else:
            (
                parse_alternative,
                alternative_context,
                remove,
            ) = ResultOut.parse_alternative(alternative)

            if parse_alternative is None:
                continue

            words = parse_alternative.split()
            alternative_tokens = fetch_tokens("de", words[-1])
            if is_token_plural(lang, alternative_tokens[0]):
                article_alternative = ""
            else:
                alternative_word = german_noun_analysis(words[-1], True)
                if alternative_word is None:
                    article_alternative = tokens[i - 1].text
                elif alternative_word["genus"] == "m":
                    article_alternative = match_masculine
                elif alternative_word["genus"] == "n":
                    article_alternative = match_neuter
                elif alternative_word["genus"] == "f" or alternative.endswith("in"):
                    article_alternative = match_feminine

        if article_alternative != "":
            article_alternative += tokens[i - 1].whitespace_

        alternatives_with_article.append(article_alternative + alternative)

    return alternatives_with_article


def sentences_matches(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    offsets,
    subcategory,
    matches,
):
    list_tokens = []

    if is_sub_category_enabled(config, subcategory):
        for match_id, start, end in matches:
            span = tokens[start:end]

            list_tokens.append(
                ResultOut.factory(
                    version,
                    config,
                    lang,
                    span.text,
                    full_text,
                    offsets,
                    subcategory,
                    span.start_char,
                    span.end_char,
                )
            )

    return list_tokens


def sentences_matcher(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    offsets,
    sentences_data,
    df_sentence,
    subcategory=None,
):
    list_tokens = []

    if not isinstance(df_sentence, list):
        if not isinstance(df_sentence, pd.DataFrame):
            return list_tokens

        df_sentence = list(df_sentence["Lemma"])

    matches = fetch_matches(lang.lang, tokens, df_sentence)

    if sentences_data is None:
        return sentences_matches(
            version,
            config,
            lang,
            full_text,
            tokens,
            offsets,
            subcategory,
            matches,
        )

    alternatives = None

    for match_id, start, end in matches:
        span = tokens[start:end]
        for sentence, subcategory, *data in sentences_data:
            if span.text.lower() == sentence.lower():
                if not is_sub_category_enabled(config, subcategory):
                    continue

                if len(data):
                    alternatives = data[0]

                list_tokens.append(
                    ResultOut.factory(
                        version,
                        config,
                        lang,
                        span.text,
                        full_text,
                        offsets,
                        subcategory,
                        span.start_char,
                        span.end_char,
                        alternatives,
                    )
                )

    return list_tokens


def regex_matches(
    version: float,
    config: Config,
    lang,
    full_text,
    offsets,
    regexes,
    subcategory=None,
):
    list_ending = []
    alternatives = None
    for regex in regexes:
        matches = re.finditer(regex, full_text)

        for span in matches:
            if type(span) != re.Match:
                continue

            text = span.group(1)
            start = span.start()
            explanation = None
            url = None
            icon = None
            # case-(in)sensitive term_replacements
            if isinstance(regexes[regex], dict):
                text = span.group(0)
                alternatives = regexes[regex]["alternatives"]
                if isinstance(regexes[regex]["explanation"], dict):
                    explanation, url, icon = map(
                        regexes[regex]["explanation"].get, ("text", "url", "icon")
                    )
            # d_f_m_regexes
            elif len(span.groups()) == 5 and subcategory == "d_and_i":
                text = span.group(0).lstrip()
                start += 1
            # m_f_regexes
            elif len(span.groups()) == 5:
                text = span.group(0).lstrip()
                start += 1

                letters = [span.group(2), span.group(3)]
                if span.group(4) is not None:
                    letters = letters + span.group(4)[1:].split("/")

                letters = list(map(lambda x: x.upper(), letters))
                is_lower = span.group(2).islower()

                veteran_letter = "V"
                diverse_letter = "D"
                if diverse_letter not in letters and "*" not in letters:
                    letters.append(diverse_letter)

                x_letter = "X"
                without_x = True
                if "X" in letters:
                    letters.remove("X")
                    without_x = False

                without_v = True
                if "V" in letters:
                    letters.remove("V")
                    without_v = False

                if "W" in letters:
                    letters.remove("W")
                    letters.append("F")

                alternative = "/".join(sorted(letters))
                if is_lower:
                    alternative = alternative.lower()
                    diverse_letter = diverse_letter.lower()
                    veteran_letter = veteran_letter.lower()
                    x_letter = x_letter.lower()

                parenthesis = False if span.group(1) is None else True
                if parenthesis:
                    alternative = "(" + alternative + ")"

                context_v = "--- include veterans"
                if lang.lang == "de":
                    context_d = "--- Divers (EU) / m. Behinderung (NA)"
                    context_remove = "--- Nutze geschlechtsneutrale Job-Titel"
                    explanation = "Nenne unterrepräsentierte Gruppen zuerst. Verlinke auf deine Leitlinie zur Gleichstellung."
                else:
                    context_d = "--- disabled (NA) / diverse (EU)"
                    context_remove = "--- Use gender neutral job title"
                    explanation = "Put underrepresented groups first and link to your equal opportunity policy"

                alternative_3 = None
                if "*" in alternative:
                    alternative_2 = alternative.replace("*", diverse_letter)
                    alternative_v = alternative_2
                    alternative_2 += context_d
                    if not without_x:
                        alternative_3 = alternative.replace("*", x_letter)
                else:
                    alternative_2 = alternative.replace(diverse_letter, "*")
                    alternative_v = alternative
                    if not without_x:
                        alternative_3 = alternative.replace(diverse_letter, x_letter)
                    alternative += context_d

                if lang.lang == "en":
                    alternative_v = alternative_v.replace(
                        diverse_letter, diverse_letter + "/" + veteran_letter
                    )

                    if without_v == False:
                        alternative = alternative_v + context_d
                    else:
                        alternative_v += context_v

                alternatives = ["- " + context_remove, alternative]

                if lang.lang == "en" and without_v:
                    alternatives.append(alternative_v)

                if lang.lang == "de" or "*" in alternative:
                    alternatives.append(alternative_2)

                if alternative_3 is not None:
                    alternatives.append(alternative_3)
            # gender inclusive ending
            elif len(span.groups()) == 2:
                text = span.group(0)
                if (
                    (
                        text[0:1].islower()
                        and span.group(2) in rules["de"]["male_articles"]
                    )
                    or text[0:1].isupper()
                    and (span.group(2)[0:2] == "in" or span.group(2)[0:5] == "innen")
                ):
                    separator = regexes[regex]
                    if separator is not None:
                        if span.group(2) in rules["de"]["male_articles"]:
                            separator = separator[0:1]
                        alternatives = [span.group(1) + separator + span.group(2)]
                else:
                    continue
            elif regexes[regex] is not None:
                alternatives = regexes[regex]

            list_ending.append(
                ResultOut.factory(
                    version,
                    config,
                    lang,
                    text,
                    full_text,
                    offsets,
                    subcategory,
                    start,
                    None,
                    alternatives,
                    None,
                    explanation,
                    url,
                    icon,
                )
            )

    return list_ending


def ub_words_phrase_matcher_de(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    offsets,
    words_data,
    sentences_data,
    df_sentence,
):
    list_tokens = []

    token = None
    for i in range(len(tokens)):
        prev_token = token
        token = tokens[i]
        for word, word_types, subcategory, alternatives in words_data:
            if not is_sub_category_enabled(config, subcategory):
                continue

            if not is_word_match(lang.lang, token, tokens, word, word_types):
                continue

            text, start, alternatives = alternatives_declension(
                lang.lang, token, alternatives, prev_token
            )

            list_tokens.append(
                ResultOut.factory(
                    version,
                    config,
                    lang,
                    text,
                    full_text,
                    offsets,
                    subcategory,
                    start,
                    None,
                    alternatives,
                )
            )

    return list_tokens + sentences_matcher(
        version,
        config,
        lang,
        full_text,
        tokens,
        offsets,
        sentences_data,
        df_sentence,
    )


def gendered_denom_analysis_de(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    offsets,
    words_data,
    false_positives,
):
    list_tokens = []

    for i in range(len(tokens)):
        for (
            word,
            word_types,
            subcategory,
            alternatives_sing,
            alternatives_plur,
        ) in words_data:
            postfix = subcategory.endswith("_base")
            if postfix:
                subcategory = subcategory.removesuffix("_base")

            if not is_sub_category_enabled(config, subcategory):
                continue

            token = tokens[i]
            match = is_word_match(
                lang.lang,
                token,
                tokens,
                word,
                word_types,
                None,
                True,
                postfix,
            )

            if not match:
                if not postfix:
                    continue

                result = german_noun_lookup(word)
                if (
                    result is None
                    or "flexion" not in result
                    or "nominativ plural" not in result["flexion"]
                    or "nominativ singular" not in result["flexion"]
                    or not token.text.endswith(
                        result["flexion"]["nominativ plural"].lower()
                    )
                ):
                    continue

                match = "postfix"
                lemma = token.lemma_.replace(
                    result["flexion"]["nominativ plural"].lower(),
                    result["flexion"]["nominativ singular"].lower(),
                )
                is_singular = False
            else:
                lemma = token.lemma_
                is_singular = is_token_singular(lang.lang, token)
                if is_singular is None:
                    continue

            if is_singular:
                alternatives = alternatives_sing
            else:
                alternatives = alternatives_plur

            if alternatives is None:
                continue

            (
                text,
                start,
                subcategory,
            ) = match_binary_inclusive_gendered_denom_analysis_de(
                version,
                config,
                false_positives,
                full_text,
                tokens,
                i,
                subcategory,
            )

            if text is None:
                continue

            if match == "postfix":
                alternatives = alternatives.copy()
                prefix = token.lemma_.removesuffix(word.lower())
                for k, alternative in enumerate(alternatives):
                    alternative = alternative.replace(word, text)
                    if alternative[0] == "~":
                        alternative = prefix + alternative[1].lower() + alternative[2:]
                    if word[0] == "A":
                        modified_word = "Ä" + word[1:]
                        modified_word_lower = "ä" + word[1:]
                        replacement = (
                            lemma[0 : -len(modified_word)] + modified_word_lower
                        )
                        alternative = alternative.replace(
                            modified_word_lower, replacement.lower()
                        )
                        alternative = alternative.replace(modified_word, replacement)

                    alternatives[k] = alternative

            if not ResultOut.genderedRolesFormatBinary(config.gendered_roles_format):
                new_alternatives = []
                for alternative in alternatives:
                    if (
                        "frau" not in alternative.lower()
                        or "mann" not in alternative.lower()
                    ):
                        new_alternatives.append(alternative)
                alternatives = new_alternatives

            flexion = fetch_flexion(token)
            if flexion is not None and "nominativ" not in flexion:
                new_alternatives = []
                for alternative in alternatives:
                    if "~" in alternative:
                        alternative_words = alternative.split("~")

                        german_noun = german_noun_analysis(alternative_words[-1])
                        if (
                            german_noun is not None
                            and "flexion" in german_noun
                            and flexion in german_noun["flexion"]
                        ):
                            alternative_words[-1] = german_noun["flexion"][flexion]
                            alternative = "~".join(alternative_words)

                    new_alternatives.append(alternative)
                alternatives = new_alternatives

            if i > 0 and is_singular:
                alternatives_with_article = fetch_alternatives_with_article(
                    tokens, i, alternatives
                )
                if alternatives_with_article is not None:
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
                    offsets,
                    subcategory,
                    start,
                    None,
                    alternatives,
                )
            )

            break

    return list_tokens


def style_word_analysis_de(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    offsets,
    df_sentences,
    words_data,
    sentences_data,
    false_positives,
):
    list_tokens = []

    token = None
    for i in range(len(tokens)):
        prev_token = token
        token = tokens[i]
        # check if the user query have false positives
        if is_false_positive(token.lemma_, false_positives):
            # recognise if there is Name of organisation or geographical name in the query
            if len(tokens.ents) > 0:
                continue

        if token.lemma_ == "aber":
            preceeding_text = full_text[max(0, token.idx - 5) : token.idx]
            if (
                re.search(r"^ *$", preceeding_text) is not None
                or re.search(r"[.!?:,]\s*$", preceeding_text, re.MULTILINE) is not None
            ):
                continue

        for word, word_types, subcategory, alternatives in words_data:
            if not is_sub_category_enabled(config, subcategory):
                continue

            if not is_word_match(lang.lang, token, tokens, word, word_types):
                continue

            text, start, alternatives = alternatives_declension(
                lang.lang, token, alternatives, prev_token
            )

            text, alternatives = detect_filler_words_at_sentence_start(
                subcategory,
                alternatives,
                text,
                full_text,
                start + len(text),
            )

            list_tokens.append(
                ResultOut.factory(
                    version,
                    config,
                    lang,
                    text,
                    full_text,
                    offsets,
                    subcategory,
                    start,
                    None,
                    alternatives,
                )
            )

    return list_tokens + sentences_matcher(
        version,
        config,
        lang,
        full_text,
        tokens,
        offsets,
        sentences_data,
        df_sentences,
    )


def word_noun(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    offsets,
    words_data,
    false_positive_matcher=None,
):
    list_tokens = []

    token = None
    for i in range(len(tokens)):
        prev_token = token
        token = tokens[i]
        for (
            word,
            word_types,
            subcategory,
            alternatives_sing,
            alternatives_plur,
            *data,
        ) in words_data:
            if not is_sub_category_enabled(config, subcategory):
                continue

            if not is_word_match(
                lang.lang, token, tokens, word, word_types, false_positive_matcher
            ):
                continue

            is_singular = is_token_singular(lang.lang, token)
            if is_singular is None:
                continue

            text = token.text
            start = token.idx

            if is_singular:
                alternatives = alternatives_sing

                text, start, alternatives = alternatives_declension(
                    lang.lang, token, alternatives, prev_token
                )
            elif len(data):
                # Secondary_subcategory
                alternatives, subcategory = plural_alternatives(
                    token,
                    alternatives_plur,
                    data[0],
                )

                if not is_sub_category_enabled(config, subcategory):
                    continue
            else:
                alternatives = alternatives_plur

            list_tokens.append(
                ResultOut.factory(
                    version,
                    config,
                    lang,
                    text,
                    full_text,
                    offsets,
                    subcategory,
                    start,
                    None,
                    alternatives,
                )
            )

    return list_tokens


def detect_filler_words_at_sentence_start(
    subcategory, alternatives, text, full_text, end
):
    if subcategory == "filler" and alternatives == ["-"] and text[0].isupper():
        match = re.search(r"(\s*,\s*)(\S+)", full_text[end : end + 30])
        if type(match) == re.Match:
            text += match.group(0)
            alternatives = [match.group(2).capitalize()]

    return text, alternatives


def token_is_conjunction(token):
    return token.text == "," or token.pos_ == "CCONJ"


def pluralize_they(tokens, i):
    token = tokens[i]
    text = token.text
    alternative = "they"

    next_i = i + 1
    if len(tokens) <= next_i:
        return text, alternative

    verb_map = {
        "is": "are",
        "has": "have",
    }

    if tokens[next_i].text in verb_map:
        text += token.whitespace_ + tokens[next_i].text
        alternative += token.whitespace_ + verb_map[tokens[next_i].text]
    else:
        # she/he builds, cleans and refurbishes houses => they build, clean and refurbish houses
        prev_token = token
        while (
            len(tokens) > next_i + 1
            and token_is_conjunction(tokens[next_i])
            and tokens[next_i + 1].text[-1] == "s"
        ) or (
            next_i == i + 1
            and tokens[next_i].text[-1] == "s"
            and "v" in fetch_word_types("en", tokens[next_i])
        ):
            if token_is_conjunction(tokens[next_i]):
                text += prev_token.whitespace_ + tokens[next_i].text
                alternative += prev_token.whitespace_ + tokens[next_i].text
                prev_token = tokens[next_i]
                next_i += 1
                if len(tokens) <= next_i:
                    break

            text += prev_token.whitespace_ + tokens[next_i].text
            ending_length = -2 if tokens[next_i].text[-2:] == "es" else -1
            alternative += prev_token.whitespace_ + tokens[next_i].text[0:ending_length]

            prev_token = tokens[next_i]
            next_i += 1
            if len(tokens) <= next_i:
                break

    return text, alternative


def rules_based_words_phrase_matcher(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    offsets,
    words_data,
    sentences_data=None,
    df_sentence=None,
    false_positive_matcher=None,
    fallback_subcategory=None,
    they=False,
):
    list_tokens = []

    alternatives = None
    subcategory = fallback_subcategory

    token = None
    for i in range(len(tokens)):
        prev_token = token
        token = tokens[i]
        for word, word_types, *data in words_data:
            if len(data):
                subcategory = data[0]

            partial_matching = subcategory.endswith("_base")
            subcategory = subcategory.removesuffix("_base")

            if partial_matching and settings.partial_matching:
                match = False
            else:
                partial_matching = False
                match = is_word_match(
                    lang.lang,
                    token,
                    tokens,
                    word,
                    word_types,
                    false_positive_matcher,
                )

            if not match:
                if (
                    not partial_matching
                    or lang.lang == "en"
                    or len(data) < 3
                    or get_proficiency_level(subcategory) != "openly_discriminating"
                    or "s" not in word_types
                ):
                    continue

                token_lower = token.text.lower()
                count = token_lower.count(word.lower())
                if count == 0:
                    continue

                if len(data) > 2 and data[2] is not None:
                    # False Positives
                    for false_positive in data[2]:
                        count = count - token_lower.count(false_positive.lower())

                if count <= 0:
                    continue

            explanation = None
            url = None
            icon = None
            text = token.text
            start = token.idx

            if len(data) > 1:
                alternatives = data[1]
                if they and "they" in alternatives:
                    text, alternative = pluralize_they(tokens, i)
                    alternatives = [alternative]
                else:
                    text, start, alternatives = alternatives_declension(
                        lang.lang, token, alternatives, prev_token
                    )

                if (
                    len(data) > 2
                    and data[2] is not None
                    and subcategory == "corporate_rules"
                ):
                    explanation, url, icon = map(data[2].get, ("text", "url", "icon"))

            if not is_sub_category_enabled(config, subcategory):
                continue

            text, alternatives = detect_filler_words_at_sentence_start(
                subcategory,
                alternatives,
                text,
                full_text,
                start + len(token.text),
            )

            list_tokens.append(
                ResultOut.factory(
                    version,
                    config,
                    lang,
                    text,
                    full_text,
                    offsets,
                    subcategory,
                    start,
                    None,
                    alternatives,
                    None,
                    explanation,
                    url,
                    icon,
                )
            )

            if get_proficiency_level(subcategory) == "openly_discriminating":
                break

    return list_tokens + sentences_matcher(
        version,
        config,
        lang,
        full_text,
        tokens,
        offsets,
        sentences_data,
        df_sentence,
        fallback_subcategory,
    )


# english function to handle homonyms
def homonyms_en(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    offsets,
    false_positive_matcher,
    words_data,
):
    list_tokens = []

    token = None
    for i in range(len(tokens)):
        prev_token = token
        token = tokens[i]
        for word, word_types, subcategory, alternatives in words_data:
            if not is_sub_category_enabled(config, subcategory):
                continue

            if not is_word_match(
                lang.lang, token, tokens, word, word_types, false_positive_matcher, False
            ):
                continue

            text, start, alternatives = alternatives_declension(
                lang.lang, token, alternatives, prev_token
            )

            list_tokens.append(
                ResultOut.factory(
                    version,
                    config,
                    lang,
                    text,
                    full_text,
                    offsets,
                    subcategory,
                    start,
                    None,
                    alternatives,
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
    offsets,
    df_sentence,
    term_list,
    lower_case=False,
):
    list_tokens = []

    matches = fetch_matches(lang.lang, tokens, list(df_sentence["Lemma"]))
    for match_id, start, end in matches:
        for (
            term,
            word_types,
            subcategory,
            alternatives,
        ) in term_list:
            if not is_sub_category_enabled(config, subcategory):
                continue

            span = tokens[start:end]
            text = span.text
            lower_case_rule = lower_case
            if lower_case and word_types != "":
                word_types, lower_case_rule, lemmatize = parse_word_types(word_types)

            if lower_case_rule:
                text = text.lower()
                term = term.lower()

            if text != term:
                continue

            list_tokens.append(
                ResultOut.factory(
                    version,
                    config,
                    lang,
                    span.text,
                    full_text,
                    offsets,
                    subcategory,
                    span.start_char,
                    span.end_char,
                    alternatives,
                )
            )

    return list_tokens


def detect_lower_cased_hashtags(
    version: float,
    config: Config,
    lang,
    full_text,
    offsets,
):
    subcategory = "style"

    list_results = []

    if lang.lang == "de":
        explanation = "Wenn du Wörter großschreibst, wissen alle gleich, was du meinst. #ZumBeispiel"
    else:
        explanation = "When you capitalize words, everyone knows right away what you mean. #ForExample"

    matches = re.finditer(r"#(\w*)", full_text)
    for span in matches:
        if type(span) == re.Match:
            text = span.group(1)

            if len(text) < 5 or any(char.isupper() for char in text):
                continue

            list_results.append(
                ResultOut.factory(
                    version,
                    config,
                    lang,
                    "#" + text,
                    full_text,
                    offsets,
                    subcategory,
                    span.start(),
                    span.end(),
                    None,
                    None,
                    explanation,
                )
            )

    return list_results


def get_emoji(emoji_text):
    return emoji.emojize(":" + emoji_text + ":", language="alias")


def get_emoji_context(alternative, lang):
    return (
        "--- "
        + emoji.demojize(alternative, language=lang)
        .replace(":", "")
        .replace("_", " ")
        .title()
    )


def detect_non_inclusive_emoji(
    version: float,
    client: str,
    config: Config,
    lang,
    full_text,
    tokens,
    offsets,
):
    list_results = []

    if client and client < VersionString("1.28.0.1"):
        return list_results

    token_count = len(tokens)
    for i in range(token_count):
        subcategory = None
        token = tokens[i]
        if not token._.is_emoji:
            continue

        # 👨🏽‍👩🏽‍👧🏽 case https://github.com/carpedm20/emoji/issues/204
        if (i + 1 < token_count and tokens[i + 1].text.endswith("\u200d")) or (
            i > 0 and tokens[i - 1].text.endswith("\u200d")
        ):
            continue

        alternatives = [get_emoji_context(token.text, lang.lang)]

        emoji_description = token._.emoji_desc
        emoji_base = emoji_description.replace(" light skin tone", "")
        emoji_base = emoji_base.replace(" ", "_")

        for emoji_config_name in rules["emoji"]:
            emoji_config = rules["emoji"][emoji_config_name]
            included = False
            for rule in emoji_config["rules"]:
                if rule in emoji_base:
                    included = rule
                    break

            if not included:
                continue

            emojis = []
            for subcategory in emoji_config["subcategory"]:
                if is_sub_category_enabled(config, subcategory):
                    emojis += emoji_config["subcategory"][subcategory]

            if emojis == []:
                continue

            if (
                "skin_tone" not in emoji_base
                and emoji_config["skin_tone"]
                and len(emojis) <= 3
            ):
                skin_tones = (
                    rules["skin_tones"]["full"]
                    if len(emojis) == 1
                    else rules["skin_tones"]["minimal"]
                )
            else:
                skin_tones = []

            for alternative_text in emojis:
                alternative_text = emoji_base.replace(rule, alternative_text)
                alternative = get_emoji(alternative_text)

                # if person is not available, then check of "woman" is available
                if ":" in alternative and emoji_config_name == "person_gender":
                    alternative_text = emoji_base.replace(rule, "woman")
                    alternative = get_emoji(alternative_text)

                if ":" not in alternative and alternative != token.text:
                    alternatives.append(
                        alternative + " " + get_emoji_context(alternative, lang.lang)
                    )

            for alternative_text in emojis:
                alternative_text = emoji_base.replace(rule, alternative_text)

                for skin_tone in skin_tones:
                    alternative_skin_tone_text = alternative_text + skin_tone
                    alternative = get_emoji(alternative_skin_tone_text)

                    # if person is not available, then check of "woman" is available
                    if ":" in alternative and emoji_config_name == "person_gender":
                        alternative_skin_tone_text = (
                            emoji_base.replace(rule, "woman") + skin_tone
                        )
                        alternative = get_emoji(alternative_skin_tone_text)

                    if ":" not in alternative and alternative != token.text:
                        alternatives.append(
                            alternative
                            + " "
                            + get_emoji_context(alternative, lang.lang)
                        )

            if len(alternatives) == 1:
                continue

            # match found
            break

        if (
            len(alternatives) == 1
            and "light skin tone" in emoji_description
            and "medium" not in emoji_description
        ):
            subcategory = "culture"
            for skin_tone in rules["skin_tones"]["all"]:
                alternative = get_emoji(emoji_base + skin_tone)
                if ":" not in alternative and alternative != token.text:
                    alternatives.append(
                        alternative + " " + get_emoji_context(alternative, lang.lang)
                    )

        if not subcategory or len(alternatives) == 1:
            continue

        list_results.append(
            ResultOut.factory(
                version,
                config,
                lang,
                token.text,
                full_text,
                offsets,
                subcategory,
                token.idx,
                None,
                alternatives,
            )
        )

    return list_results


# want to server to run app.py in the folder app as main app, port=8000 is defaut port for the fast api
# reload=True is debag mode in Flask is on, to set =False, when deploy the app to the production
# might be added host="0.0.0.0"
if __name__ == "__main__":  # pragma: no cover
    # If this is being ran directly as a script, run an internal uvicorn server
    # to service API requests
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level=settings.logging_config_level)
