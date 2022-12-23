import re
import uvicorn
import json
import secrets
from aiohttp import ClientSession, TCPConnector, ClientError
import copy
from typing import Optional, Union
from collections import defaultdict

from spacy.tokens import Doc
from spacy.matcher import PhraseMatcher, Matcher
import pandas as pd

from inflex import Noun, Verb, Adjective

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

from fastapi_microsoft_identity import validate_scope, get_token_claims

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
    LangWithAutoType,
    LangVariantType,
    SingularTheyType,
    Language,
    RequestIn,
    Result,
    ResultOut,
    ResultsOut,
    ResultsOut1_1,
    UserConfRequest,
    OrganizationConfRequest,
    ConfResponse,
    UserConfResponse,
    RuleConfig,
    ResultConf,
    ResultConf1_1,
    ErrorMessage,
    PrettyJSONResponse,
)
from app.lang_detection import LangDetection
from app.categories import categories
from app.settings import get_settings
from app.logger import set_up_logger
from app.redis_setup import set_up_redis
from app.languagetool import get_languagetool_url
from app.azure_ad_b2c import initialize_aadb2c
from app.model import model
from app.rules import rules
from app.sentry import set_up_sentry_sdk

version = "1.39.9"

settings = get_settings()
logging = set_up_logger(settings)
sentry_sdk = set_up_sentry_sdk(version, settings)
languagetool_url = get_languagetool_url(settings)
redis = set_up_redis(settings)
lang_detection = LangDetection()
initialize_aadb2c(settings)

logging.debug("app started with settings: %s", settings)

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

    user_request_in = RequestIn(text=body["text"])
    text, lang, limit_reached = fetch_text(user_request_in)

    if lang is None:
        await respond(f"Witty could not determine a language for '{text}'.")
        return

    configs = {}

    try:
        user = await client.users_info(user=body["user_id"])
        configs = await fetch_configs_for_request(
            user_request_in, user.data["user"]["profile"]["email"]
        )
    except KeyError:
        pass

    if configs == {} and settings.slack_organization_id:
        configs = await fetch_organization_configs_for_request(
            user_request_in, settings.slack_organization_id
        )

    user_request_in.config.__setattr__("alternatives_max_count", None)
    results = await apply_language_rules(
        2.0, user_request_in.config, configs, lang, text
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
            issue_text = f"#{i+1} Matched Text: {result.text} (category {result.category}, gravity {result.gravity})\n"

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


app = FastAPI(
    title="Witty NLP API",
    version=version,
    terms_of_service=settings.terms_of_service,
    contact=settings.contact,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


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

# https://languagetool.org/development/api/org/languagetool/rules/Categories.html
lt_style_categories = [
    "PLAIN_ENGLISH",
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


@app.get("/lt", include_in_schema=not settings.is_prod)
def get_lt(username: str = Depends(fetch_current_username)):
    return languagetool_url


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
    url = "https://www.witty.works/editor"
    status_code = 301

    if not settings.is_prod and settings.testing == False:  # pragma: no cover
        url = "/docs"
        status_code = 302

    return RedirectResponse(url=url, status_code=status_code)


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

    configs = await fetch_configs_for_request(user_request_in, user_email)

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
    "/auth",
    response_model=Union[ResultConf1_1, dict, None],
    response_model_exclude_none=True,
    dependencies=[Depends(HTTPBearer(auto_error=False))],
)
async def post_auth_1_1(request: Request, response: Response):
    user_email = fetch_user(request)
    if not user_email:
        return None

    configs = await fetch_configs_for_request(RequestIn(text=""), user_email)
    config = fetch_result_conf(configs, 1.1)
    if config is None and user_email:
        config = {}

    return config


@app.post(
    "/v2.0/auth",
    response_model=Union[ResultConf, dict, None],
    response_model_exclude_none=True,
    dependencies=[Depends(HTTPBearer(auto_error=False))],
)
async def post_auth_2_0(request: Request, response: Response):
    user_email = fetch_user(request)
    if not user_email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
        )

    configs = await fetch_configs_for_request(RequestIn(text=""), user_email)
    if configs == {}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
        )

    config = fetch_result_conf(configs, 2.0)

    if "team_analytics" in configs and not configs["team_analytics"]:
        config.organization_id = None

    return config


@app.get(
    "/debug/spacy",
    include_in_schema=not settings.is_prod,
    response_class=PrettyJSONResponse,
)
async def get_debug_spacy(
    text: str,
    locale: LangWithAutoType = "auto",
    username: str = Depends(fetch_current_username),
):
    if locale == "auto" or len(locale) == 2:
        locale = lang_detection.get_locale(
            text,
            locale,
            ["en", "de"],
        )

    if locale is None:
        raise HTTPException(status_code=422, detail="Could not determine language")

    lang = Language(locale)

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
                "word_types": fetch_word_types(token, lang),
                "morph": token.morph.get("Number"),
                "foreign": token.morph.get("Foreign"),
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


@app.get("/categories")
def get_categories(lang: LangType = "de"):
    return categories_with_labels[lang]


@app.post(
    "/v1.1/check",
    response_model=Union[ResultsOut1_1, Result],
    response_model_exclude_none=True,
    dependencies=[Depends(HTTPBearer(auto_error=False))],
)
async def post_check_v1_1(
    request: Request,
    response: Response,
    user_request_in: RequestIn,
):
    version = 1.1
    results, language, limit_reached, configs, user_email = await check(
        version, request, response, user_request_in
    )

    config = fetch_result_conf(configs, version)
    if config is None and user_email:
        config = {}

    if isinstance(results, Result):
        return results

    return ResultsOut1_1(
        results=results,
        language=language,
        limit_reached=limit_reached,
        organization_config=config,
    )


@app.post(
    "/v2.0/check",
    response_model=Union[ResultsOut, Result],
    response_model_exclude_none=True,
    dependencies=[Depends(HTTPBearer(auto_error=False))],
)
async def post_check_v2_0(
    request: Request,
    response: Response,
    user_request_in: RequestIn,
):
    results, language, limit_reached, configs, user_email = await check(
        2.0, request, response, user_request_in
    )

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


@app.post(
    "/v2.1/check",
    response_model=Union[ResultsOut, Result],
    response_model_exclude_none=True,
    dependencies=[Depends(HTTPBearer(auto_error=False))],
)
async def post_check_v2_1(
    request: Request,
    response: Response,
    user_request_in: RequestIn,
):
    results, language, limit_reached, configs, user_email = await check(
        2.1, request, response, user_request_in
    )

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


# data exchange routes
@app.get("/lemmatize")
async def lemmatize(
    text: str,
    locale: Union[LangVariantType, LangType],
    username: str = Depends(fetch_current_username),
):
    lang = Language(locale)

    tokens = fetch_tokens(lang, text)
    if len(tokens) != 1:
        return None

    return tokens[0].lemma_


@app.post(
    "/organization/rules",
    response_model=ConfResponse,
    response_model_exclude_none=True,
)
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
    "/organization/rules",
    status_code=status.HTTP_204_NO_CONTENT,
)
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
    "/organization/rules",
    response_model=ConfResponse,
    response_model_exclude_none=True,
    responses={404: {"model": ErrorMessage}},
)
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
    "/user/rules",
    response_model=UserConfResponse,
    response_model_exclude_none=True,
)
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
    "/user/rules",
    status_code=status.HTTP_204_NO_CONTENT,
)
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
    "/user/rules",
    response_model=UserConfResponse,
    response_model_exclude_none=True,
    responses={404: {"model": ErrorMessage}},
)
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


def is_token_singular(token, lang: Language):
    number = token.morph.get("Number")
    if number:
        return "Sing" in number

    if token.text[:1:] != "s":
        return True
    elif lang.lang == "de":
        return None

    return False


def apply_configs(user_request_in: RequestIn, configs: dict, plan: str):
    disabled_categories = user_request_in.config.disabled_categories

    for config in configs:
        data = configs[config]
        if data is not None and data["status"] == "force":
            if config in ["inclusive", "style", "orthography"]:
                if data["value"]:
                    if config in disabled_categories:
                        disabled_categories.remove(config)
                elif config not in disabled_categories:
                    disabled_categories.append(config)
            elif config == "store_context":
                if plan == "witty_teams" and not data["value"]:
                    user_request_in.config.__setattr__("store_context", False)
            else:
                user_request_in.config.__setattr__(config, data["value"])

    user_request_in.config.__setattr__("disabled_categories", disabled_categories)
    user_request_in.config.__setattr__("plan", plan)


async def fetch_configs_for_request(
    user_request_in: RequestIn, user_email=Optional[str]
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

    apply_configs(user_request_in, configs["config"], configs["plan"])

    if "organization_config" in configs:
        apply_configs(user_request_in, configs["organization_config"], configs["plan"])

        configs["term_replacements"] |= configs["organization_term_replacements"]
        configs["false_positives"] = list(
            set(configs["false_positives"] + configs["organization_false_positives"])
        )

    if configs["plan"] != "witty_teams":
        user_request_in.config.maximum_importance = min(
            2.0, user_request_in.config.maximum_importance
        )

    return configs


async def fetch_organization_configs_for_request(
    user_request_in: RequestIn, organization_id=Optional[str]
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

    apply_configs(user_request_in, configs["config"], configs["plan"])

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


async def check(
    version: float,
    request: Request,
    response: Response,
    user_request_in: RequestIn,
):
    if version != 1.1 and version != 2.0 and version != 2.1:  # pragma: no cover
        response.status_code = status.HTTP_400_BAD_REQUEST
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Version not supported: " + str(version),
        )

    user_email = fetch_user(request)
    if version == 2.0 and not user_email:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
        )

    configs = await fetch_configs_for_request(user_request_in, user_email)

    text, lang, limit_reached = fetch_text(user_request_in)

    if lang is None:
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        results = Result.factory("Language could not be determined")
        language = None
        configs = {}
    else:
        results = await apply_language_rules(
            version, user_request_in.config, configs, lang, text
        )

        language = lang.lang

    return results, language, limit_reached, configs, user_email


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


def fetch_result_conf(
    configs: dict,
    version: float,
):
    if "config" not in configs:
        return None

    if "organization_config" in configs:
        organization_config = RuleConfig.parse_obj(configs["organization_config"])
    else:
        organization_config = None

    plan = configs["plan"]

    if version < 2.0:
        return ResultConf1_1(
            id=configs["organization_id"],
            name=configs["organization_name"],
            plan=plan,
            config=organization_config,
        )

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
    version: float, config: Config, lang: Language, text: str, result
):
    list_results = []
    ignore = ["@", "#"]

    gendered_denom = (
        lang.lang == "de"
        and is_sub_category_enabled(version, config, "gendered_denominations_ending")
        and ResultOut.genderedRolesFormatInclusive(config.gendered_roles_format)
    )

    for match in result["matches"]:
        start = int(match["offset"])
        end = start + int(match["length"])
        highlight_text = text[start:end]

        # Ignore capitalization after German salutation
        if (
            start > 5
            and match["rule"]["id"] == "DE_CASE"
            and text.lstrip().startswith(
                (
                    "Hallo",
                    "Sehr geehrte",
                    "Liebe",
                )
            )
            and "".join(text[0:start].split()).endswith(",")
        ):
            continue

        if (
            lang.lang == "de"
            and config.german_gender_ending == ":in"
            and match["rule"]["id"] == "LEERZEICHEN_HINTER_DOPPELPUNKT"
            and text[start + 1 : end] in rules["de-DE"]["male_articles"]
        ):
            continue

        # ignore text that starts with @ or #
        if highlight_text[0:1] in ignore or (
            start > 0 and text[start - 1 : start] in ignore
        ):
            continue

        # ignore german gender ending as spelling mistakes
        if gendered_denom and has_gender_denom_ending(
            highlight_text, text, start, config
        ):
            continue

        try:
            category = "orthography"
            subcategory = match["rule"]["category"]["id"]
            if subcategory in lt_style_categories:
                category = "style"

            if subcategory == "DIFFICULT_WORDS":
                category = "style"
                if match["rule"]["id"] == "ABKUERZUNG":
                    subcategory = "abbreviation"
                elif (
                    match["rule"]["id"] == "ANGLIZISMEN"
                    or "Fremdwörter" in match["message"]
                ):
                    subcategory = "anglicism"
                else:
                    subcategory = "simple_language"
            elif match["rule"]["category"]["name"] == "Leichte Sprache":
                category = "style"
                subcategory = "simple_language"
            else:
                subcategory = subcategory.lower()
                if subcategory == "style":
                    subcategory = "general_style"
                elif subcategory not in categories:
                    subcategory = category
        except KeyError:
            subcategory = category

        if not is_sub_category_enabled(version, config, subcategory):
            continue

        alternatives = fetch_alternatives(match)

        label = match["shortMessage"]
        if label == "":
            try:
                label = match["rule"]["category"]["name"]
            except KeyError:
                pass

        if category != "style" or (
            subcategory != "abbreviation" and subcategory != "anglicism"
        ):
            explanation = match["message"]
            # may be removed once updated to LT 6.0 https://github.com/languagetool-org/languagetool/commit/e4f7d6a677483b069fd98dfc461a41623618767b
            if explanation.startswith("Das Nomen „Trans"):
                continue
        else:
            explanation = None

        list_results.append(
            ResultOut.factory(
                version,
                config,
                lang,
                highlight_text,
                text,
                category,
                subcategory,
                start,
                end,
                alternatives,
                label,
                explanation,
            )
        )

    return list_results


async def apply_languagetool_rules(
    version: float, config: Config, lang: Language, text: str
):
    list_results = []

    async with ClientSession(
        connector=TCPConnector(verify_ssl=settings.languagetool_verify_ssl)
    ) as session:

        payload = {
            "text": text,
            "language": lang.locale,
        }

        if config.simple_language and payload["language"] == "de-DE":
            payload["language"] += "-x-simple-language"

        if config.primary_language is not None:
            payload["motherTongue"] = config.primary_language

        if is_sub_category_enabled(version, config, "orthography"):
            disabled_categories = [
                "GENDER_NEUTRALITY",
                "COLLOQUIALISMS",
            ]

            if "casing" in config.disabled_categories:
                disabled_categories += ["CASING"]

            if "style" in config.disabled_categories:
                disabled_categories += lt_style_categories

            payload["disabledCategories"] = disabled_categories
        elif is_sub_category_enabled(version, config, "style"):
            payload["enabledCategories"] = lt_style_categories
        else:
            return []

        async with session.post(languagetool_url + "/check", data=payload) as r:
            try:
                if r.status != 200:  # pragma: no cover
                    result = await r.text()
                    logging.error(result)

                    raise Exception(result)

                result = await r.json()
                list_results = languagetool_matches(version, config, lang, text, result)
            except ClientError as err:  # pragma: no cover
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


def fetch_tokens(lang: Language, text: str):
    # apply SpaCy pre-built model
    return model[lang.lang](text.rstrip().replace("\n", " "))


# matcher to false positives
def is_false_positive_match(list_false_positive, tokens, token):
    if list_false_positive is None:
        return False

    for match_id, start, end in list_false_positive:
        span_false = tokens[start:end]
        if token.idx in range(span_false.start_char, span_false.end_char):
            return True

    return False


# create false positives patterns based on false positives column
def false_pattern_match(tokens, lang):
    matcher = Matcher(model[lang.lang].vocab)

    for false_positive in rules[lang.lang]["pattern_false_positives"]:
        matcher.add("FalsePositivesList", false_positive)

    return matcher(tokens)


def fetch_false_positive_matcher(tokens, lang):
    # create false positives list
    phrase_matches_false = fetch_matches(tokens, rules["en"]["list_false_column"])
    word_matches_false = false_pattern_match(tokens, lang)
    return list(set(phrase_matches_false + word_matches_false))


def fetch_matches(tokens, phrases):
    # Phrase matcher part to handle False positives with two words and special symbols
    matcher = PhraseMatcher(model[lang.lang].vocab, attr="LOWER")

    # Only run model.make_doc to speed things up
    patterns = [model[lang.lang].make_doc(text) for text in phrases]
    matcher.add("TerminologyList", patterns)
    return matcher(tokens)


async def apply_language_rules(
    version: float, config: Config, configs: dict, lang: Language, text: str
):
    tokens = fetch_tokens(lang, text)

    list_results = []
    if is_sub_category_enabled(
        version, config, "orthography"
    ) or is_sub_category_enabled(version, config, "style"):
        try:
            list_results += await apply_languagetool_rules(version, config, lang, text)
        except Exception as err:
            if not settings.is_prod:  # pragma: no cover
                raise err

    if lang.lang == "de":
        list_results += german_rules(version, config, lang, tokens, text)
    else:
        list_results += english_rules(version, config, lang, tokens, text)

    if "term_replacements" in configs:
        term_replacements = {
            "Lemma": [],
            "Word_Type": [],
            "Alt_split": [],
            "Primary_subcategory": [],
            "Explanation": [],
        }

        for term in configs["term_replacements"]:
            term_replacement = configs["term_replacements"][term]

            if (
                "lang" in term_replacement
                and term_replacement["lang"] is not None
                and term_replacement["lang"] != lang.lang
            ):
                continue

            if "word_type" in term_replacement:
                word_type = term_replacement["word_type"]
            else:
                word_type = "-"

            term_replacements["Lemma"].append(term)
            term_replacements["Word_Type"].append(word_type)
            term_replacements["Alt_split"].append(term_replacement["alternatives"])
            term_replacements["Primary_subcategory"].append("corporate_rules")
            term_replacements["Explanation"].append(term_replacement["explanation"])

        term_replacements = list(
            zip(
                term_replacements["Lemma"],
                term_replacements["Word_Type"],
                term_replacements["Alt_split"],
                term_replacements["Primary_subcategory"],
                term_replacements["Explanation"],
            )
        )

        list_results += rules_based_words_phrase_matcher(
            version,
            config,
            lang,
            text,
            tokens,
            "corporate_rules",
            term_replacements,
        )

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


def is_sub_category_enabled(version: float, config: Config, subcategory: str):
    if (
        subcategory not in categories
        or categories[subcategory]["category"] in config.disabled_categories
    ):
        return False

    if (
        version >= 2.1
        and config.plan == "witty_free"
        and settings.hide_details_for_witty_free
    ):
        return True

    return float(config.maximum_importance) >= float(
        categories[subcategory]["importance"]
    )


def german_rules(version: float, config: Config, lang: Language, tokens, text: str):
    list_full = []

    if is_sub_category_enabled(version, config, "abbreviation"):
        list_full += literal_match(
            version,
            config,
            lang,
            text,
            tokens,
            rules["de-DE"]["df_abbreviation"],
            rules["de-DE"]["abbreviation"],
            True,
        )

    if is_sub_category_enabled(version, config, "openly_discriminating"):
        list_full += rules_based_words_phrase_matcher(
            version,
            config,
            lang,
            text,
            tokens,
            "openly_discriminating",
            rules["de-DE"]["open_disc_words_data"],
            rules["de-DE"]["open_disc_sentences_data"],
            rules["de-DE"]["df_open_dis_sentence"],
        )

    if is_sub_category_enabled(version, config, "gendered"):
        list_full += (
            rules_based_words_phrase_matcher(
                version,
                config,
                lang,
                text,
                tokens,
                "gendered",
                rules["de-DE"]["gender_words_data_no_noun"],
                rules["de-DE"]["gender_sentences_data"],
                rules["de-DE"]["df_gendered_sentences"],
            )
            + gendered_denom_analysis_de(
                version,
                config,
                lang,
                text,
                tokens,
                rules["de-DE"]["gender_words_data"],
                rules["de-DE"]["false_positives"].gender,
            )
            + regex_matches(
                version,
                config,
                lang,
                text,
                categories["gendered"]["category"],
                "gender_specific_abbreviation",
                rules["m_f_regexes"],
            )
        )

    if is_sub_category_enabled(
        version, config, "gendered_denominations_ending"
    ) and ResultOut.genderedRolesFormatInclusive(config.gendered_roles_format):
        subcategory = "gendered_denominations_ending"
        category = categories[subcategory]["category"]
        regexes = {}
        for ending, regex in config._gendereddenom_ending.items():
            if (
                config.german_gender_ending == ending
                # avoid issues with LinkedIn
                or ending == GermanGenderEndingType.CAPITAL_LETTER
            ):
                continue

            regexes[regex] = [config.german_gender_ending]

            if ending == ":in":
                regexes[r"\s((\S+):(\S+))"] = config.german_gender_ending[0:1]
            elif ending == "*in":
                regexes[r"\s((\S+)\*(\S+))"] = config.german_gender_ending[0:1]

        list_full += regex_matches(
            version,
            config,
            lang,
            text,
            category,
            subcategory,
            regexes,
        )

    if is_sub_category_enabled(version, config, "unconscious_bias"):
        list_full += ub_words_phrase_matcher_de(
            version,
            config,
            lang,
            text,
            tokens,
            rules["de-DE"]["bias_words_data_no_plur"],
            rules["de-DE"]["bias_sentences_data"],
            rules["de-DE"]["df_ub_sentences"],
            "unconscious_bias",
        ) + word_noun(
            version,
            config,
            lang,
            text,
            tokens,
            rules["de-DE"]["bias_words_data_noun"],
            "unconscious_bias",
        )

    if is_sub_category_enabled(version, config, "communal"):
        list_full += rules_based_words_phrase_matcher(
            version,
            config,
            lang,
            text,
            tokens,
            "inclusive",
            rules["de-DE"]["df_communal_words"],
            None,
            [],
            [],
            "communal",
        )

    if is_sub_category_enabled(version, config, "d_and_i"):
        list_full += rules_based_words_phrase_matcher(
            version,
            config,
            lang,
            text,
            tokens,
            "inclusive",
            rules["de-DE"]["df_d_and_i_words"],
            None,
            rules["de-DE"]["df_terms_d_and_i_words"],
            [],
            "d_and_i",
        )

        subcategory = "d_and_i"
        category = categories[subcategory]["category"]
        regexes = {config._gendereddenom_ending[config.german_gender_ending]: None}
        if config.german_gender_ending == ":in":
            regexes[r"\s((\S+):(\S+))"] = None
        elif config.german_gender_ending == "*in":
            regexes[r"\s((\S+)\*(\S+))"] = None

        regexes.update(rules["d_f_m_regexes"])

        list_full += regex_matches(
            version, config, lang, text, category, subcategory, regexes
        )

    if is_sub_category_enabled(version, config, "style"):
        list_full += style_word_analysis_de(
            version,
            config,
            lang,
            text,
            tokens,
            rules["de-DE"]["terms_style"],
            rules["de-DE"]["style_words_data"],
            rules["de-DE"]["style_sentences_data"],
            rules["de-DE"]["false_positives"].style,
        )

        list_full += detect_lower_cased_hashtags(
            version,
            config,
            lang,
            text,
            "style",
            "style",
        )

    return list_full


def english_rules(version: float, config: Config, lang: Language, tokens, text: str):
    list_full = []

    words_data_en = defaultdict(list)
    gendered_words_data_en = defaultdict(list)
    sentences_data_en = defaultdict(list)
    matches_false = fetch_false_positive_matcher(tokens, lang)

    if lang.locale == "en-GB":
        words_data_en["od"] = rules["en-GB"]["open_disc_words_data"]
        words_data_en["ge"] = rules["en-GB"]["gender_words_data"]
        words_data_en["ge-singular-they"] = (
            rules["en-GB"]["gender_words_data"]
            + rules["en-GB"]["bias_singular_they_alternatives"]
        )
        words_data_en["style"] = rules["en-GB"]["style_words_data"]
        words_data_en["bias"] = rules["en-GB"]["bias_words_data"]
        words_data_en["homonym"] = rules["en-GB"]["homonyms_word"]
        words_data_en["abbr"] = rules["en-GB"]["abbreviation"]

        inclusive_words_data_en = rules["en-GB"]["inclusive_words_data"]
        gendered_words_data_en["gendered"] = rules["en-GB"]["gender_noun_words_data"]
        gendered_words_data_en["bias"] = rules["en-GB"]["gender_bias_words_data"]
        inclusive_sentences_data_en = rules["en-GB"]["inclusive_sentences_data"]
        sentences_data_en["od"] = rules["en-GB"]["open_dis_sentences"]
        sentences_data_en["ge"] = rules["en-GB"]["gender_sentences_data"]
        sentences_data_en["style"] = rules["en-GB"]["style_sentences_data"]
        sentences_data_en["bias"] = rules["en-GB"]["bias_sentences_data"]
    else:
        words_data_en["od"] = rules["en-US"]["open_disc_words_data"]
        words_data_en["ge"] = rules["en-US"]["gender_words_data"]
        words_data_en["ge-singular-they"] = (
            rules["en-US"]["gender_words_data"]
            + rules["en-US"]["bias_singular_they_alternatives"]
        )
        words_data_en["style"] = rules["en-US"]["style_words_data"]
        words_data_en["bias"] = rules["en-US"]["bias_words_data"]
        words_data_en["homonym"] = rules["en-US"]["homonyms_word"]
        words_data_en["abbr"] = rules["en-US"]["abbreviation"]

        inclusive_words_data_en = rules["en-US"]["inclusive_words_data"]
        gendered_words_data_en["gendered"] = rules["en-US"]["gender_noun_words_data"]
        gendered_words_data_en["bias"] = rules["en-US"]["gender_bias_words_data"]
        inclusive_sentences_data_en = rules["en-US"]["inclusive_sentences_data"]
        sentences_data_en["od"] = rules["en-US"]["open_dis_sentences"]
        sentences_data_en["ge"] = rules["en-US"]["gender_sentences_data"]
        sentences_data_en["style"] = rules["en-US"]["style_sentences_data"]
        sentences_data_en["bias"] = rules["en-US"]["bias_sentences_data"]

    list_full += homonyms_en(
        version,
        config,
        lang,
        text,
        tokens,
        matches_false,
        words_data_en["homonym"],
    )

    if is_sub_category_enabled(version, config, "abbreviation"):
        list_full += literal_match(
            version,
            config,
            lang,
            text,
            tokens,
            rules[lang.locale]["df_abbreviation"],
            words_data_en["abbr"],
            True,
        )

    if is_sub_category_enabled(version, config, "openly_discriminating"):
        list_full += rules_based_words_phrase_matcher(
            version,
            config,
            lang,
            text,
            tokens,
            "openly_discriminating",
            words_data_en["od"],
            sentences_data_en["od"],
            rules[lang.locale]["df_open_dis_sentence"],
            matches_false,
        )

    if is_sub_category_enabled(version, config, "gendered"):
        if config.singular_they == SingularTheyType.ALL_PRONOUNS:
            list_full += rules_based_words_phrase_matcher(
                version,
                config,
                lang,
                text,
                tokens,
                "gendered",
                words_data_en["ge-singular-they"],
                sentences_data_en["ge"],
                rules[lang.locale]["df_gendered_sentence"],
                matches_false,
            )
        else:
            list_full += rules_based_words_phrase_matcher(
                version,
                config,
                lang,
                text,
                tokens,
                "gendered",
                words_data_en["ge"],
                sentences_data_en["ge"],
                rules[lang.locale]["df_gendered_sentence"],
                matches_false,
            )
        list_full += word_noun(
            version,
            config,
            lang,
            text,
            tokens,
            gendered_words_data_en["gendered"],
            "gendered",
            matches_false,
        ) + regex_matches(
            version,
            config,
            lang,
            text,
            categories["gendered"]["category"],
            "gender_specific_abbreviation",
            rules["m_f_regexes"],
        )

    if is_sub_category_enabled(version, config, "inclusive"):

        if is_sub_category_enabled(version, config, "d_and_i"):
            subcategory = "d_and_i"
            category = categories[subcategory]["category"]

            list_full += regex_matches(
                version,
                config,
                lang,
                text,
                category,
                subcategory,
                rules["d_f_m_regexes"],
            )

        list_full += rules_based_words_phrase_matcher(
            version,
            config,
            lang,
            text,
            tokens,
            "inclusive",
            inclusive_words_data_en,
            inclusive_sentences_data_en,
            rules[lang.locale]["df_inclusive_sentence"],
            matches_false,
        )

    if is_sub_category_enabled(version, config, "style"):
        list_full += rules_based_words_phrase_matcher(
            version,
            config,
            lang,
            text,
            tokens,
            "style",
            words_data_en["style"],
            sentences_data_en["style"],
            rules[lang.locale]["df_style_sentence"],
            matches_false,
        )

        list_full += detect_lower_cased_hashtags(
            version,
            config,
            lang,
            text,
            "style",
            "style",
        )

    if is_sub_category_enabled(version, config, "unconscious_bias"):
        list_full += rules_based_words_phrase_matcher(
            version,
            config,
            lang,
            text,
            tokens,
            "unconscious_bias",
            words_data_en["bias"],
            sentences_data_en["bias"],
            rules[lang.locale]["df_ub_sentence"],
            matches_false,
        ) + word_noun(
            version,
            config,
            lang,
            text,
            tokens,
            gendered_words_data_en["bias"],
            "unconscious_bias",
            matches_false,
        )

    return list_full


def parse_word_types(word_types, lower_case=True):
    lemmatize = True

    if word_types is None:
        return [], lower_case, lemmatize

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

    return word_types.split("+"), lower_case, lemmatize


def is_word_match(
    token, tokens, lang, word, word_types, matches_false=None, lower_case=True
):
    word_types, lower_case, lemmatize = parse_word_types(word_types, lower_case)

    if lemmatize:
        token_word = token.lemma_
    else:
        token_word = token.text

    if lower_case and (lang.lang == "en" or "s" not in word_types):
        token_word = token_word.lower()

    if token_word != word:
        return False

    if not check_word_types(token, lang, word_types, True):
        return False

    return is_false_positive_match(matches_false, tokens, token) == False


"""Function to catch the words related to False Positive in the user query"""


def is_false_positive(word, false_positive):
    for item in false_positive:
        if word == item:
            return True

    return False


"""Function to change adjectives to -en form in alternatives"""


def fetch_word_types(token, lang, word_types=[], single_word=None):
    if "adv" in word_types and token.pos_ == "ADV":
        return ["adv"]

    if token.pos_ == "VERB":
        if lang.lang == "de" and "a" in word_types:
            return "a"

        return "v"

    if token.pos_ == "NOUN" or token.pos_ == "PRON":
        return ["s"]

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
        return ["a"]

    if token.tag_ == "NN":
        return ["s"]

    if token.pos_ == "PROPN" and single_word is not None and len(word_types):
        return word_types[0:1]

    return []


def check_word_types(token, lang, word_types=[], single_word=None):
    if word_types == []:
        return True

    return word_types_overlap(
        fetch_word_types(token, lang, word_types, single_word), word_types
    )


def add_declension_german(text, ending):
    if text[-1] == "s":
        text += "s"
    elif text[-1] == "e" and ending[0] == "e":
        text = text[0:-1]
    elif text[-2:] == "em":
        return text

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
        logging.error(
            "Unable to determine german noun data for: %s",
            word,
        )

        return None

    result = result[0]

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

        return result

    if genus_only:
        result = determine_genus_from_ending(
            word, rules["de"]["secondary_german_genus_endings"]
        )

    return result


def align_noun_form(lang, a_token, b_token):
    a_text = a_token.text
    b_text = b_token.text

    if a_token.morph.get("Number") == b_token.morph.get("Number"):
        return b_text

    if lang.lang == "en":
        if b_token.morph.get("Number") == ["Sing"]:
            return Noun(b_text).plural()

        return Noun(b_text).singular()
    elif lang.lang == "de":
        a_word = german_noun_analysis(a_text)
        if a_word is None:
            return b_text

        b_word = german_noun_analysis(b_text)
        if b_word is None:
            return b_text

        for flexion, value in a_word["flexion"].items():
            if value != a_text:
                continue

            flexion = flexion.split()
            flexion = flexion[0] + " " + flexion[1]

            if flexion in b_word["flexion"]:
                return b_word["flexion"][flexion]

            key = flexion + " 1"
            if key not in b_word["flexion"]:
                key = flexion + " stark"

            if key in b_word["flexion"]:
                return b_word["flexion"][key]

    return b_text


def align_adjective_form(lang, a_token, b_token):
    if lang.lang == "en":
        a_text = a_token.text
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
    elif lang.lang == "de":
        ending = a_token.text[len(a_token.lemma_) :]
        return add_declension_german(b_token.text, ending)

    return b_token.text


def align_verb_form(lang, a_token, b_token):
    if lang.lang == "en":
        a_text = a_token.text
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
    elif lang.lang == "de":
        ending = a_token.text[len(a_token.lemma_) :]
        return add_declension_german(b_token.text, ending)

    return b_token.text


def alternative_declension(token, word_types, lang, alternative):
    text = token.text
    if text == token.lemma_:
        return alternative

    if ResultOut.isInspirationAlternative(text, alternative):
        return alternative

    new_alternative = ""
    previous = False
    tokens = fetch_tokens(lang, alternative)
    for alternative_token in reversed(tokens):
        alternative_text = alternative_token.text
        if alternative_text in rules[lang.lang]["conjunctions"]:
            previous = False
        else:
            if len(tokens) == 1:
                # in this case we just assume it is the same to avoid issues with word type detection
                alternative_word_types = word_types
            else:
                alternative_word_types = fetch_word_types(
                    alternative_token, lang, word_types, False
                )

            if "s" in word_types and "s" in alternative_word_types:
                alternative_text = align_noun_form(lang, token, alternative_token)
            elif previous == False and word_types_overlap(
                word_types, alternative_word_types
            ):
                previous = True
                if "a" in alternative_word_types:
                    alternative_text = align_adjective_form(
                        lang, token, alternative_token
                    )
                elif "v" in alternative_word_types:
                    alternative_text = align_verb_form(lang, token, alternative_token)

        new_alternative = (
            alternative_text + alternative_token.whitespace_ + new_alternative
        )

    return new_alternative


def alternatives_declension(token, lang, alternatives):
    word_types = fetch_word_types(token, lang)
    if word_types == []:
        return alternatives

    return [
        alternative_declension(token, word_types, lang, alternative).strip()
        for alternative in alternatives
    ]


def plural_alternatives_en(
    token,
    alternative_plur,
    second_subcategory,
):
    return [
        item for item in alternative_plur if item != token.text.lower()
    ], second_subcategory


def ignore_binary_inclusive_gendered_denom_analysis_de(
    lang,
    tokens,
    false_positives,
):
    matches = fetch_matches(tokens, false_positives)
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


def fetch_matching_flexions(text, word, is_plural_check=False):
    matches = {
        "is_plural": False,
        "forms": [],
    }

    if "flexion" in word:
        for flexion, value in word["flexion"].items():
            if value == text:
                words = flexion.replace("*", "").split()
                if len(words) != 2:
                    continue

                if "plural" in words[1]:
                    matches["is_plural"] = True
                    if is_plural_check:
                        break

                matches["forms"].append(words[0])

    return matches


def fetch_alternatives_with_article(tokens, i, alternatives):
    text = tokens[i].text
    word = german_noun_analysis(text)
    if word is None:
        return None

    matches = fetch_matching_flexions(text, word)
    if len(matches["forms"]) == 0:
        return None

    matched_form = None
    article_text = tokens[i - 1].text.lower()
    match_masculine = None
    match_feminine = None
    match_neuter = None
    match_alternative = None
    for form, masculine, feminine, neuter, plural, alternative in rules["de-DE"][
        "articles"
    ]:
        if form not in matches["forms"]:
            continue

        article_to_check = None
        if word["genus"] == "m":
            article_to_check = masculine
        elif word["genus"] == "f":
            article_to_check = feminine
        elif word["genus"] == "n":
            article_to_check = neuter

        if article_text == article_to_check:
            if matched_form is None:
                matched_form = form
                match_masculine = masculine
                match_feminine = feminine
                match_neuter = neuter
                match_alternative = alternative
            elif matched_form != form:
                if match_masculine != masculine:
                    match_masculine = False

                if match_feminine != feminine:
                    match_feminine = False

                if match_neuter != neuter:
                    match_neuter = False

                if match_alternative != alternative:
                    match_alternative = False

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
            if "---" in alternative:
                alternative, alternative_context = ResultOut.parse_alternative_context(
                    alternative
                )

            words = alternative.split()
            word = german_noun_analysis(words[-1], True)
            if word is None:
                article_alternative = tokens[i - 1].text
            else:
                matches = fetch_matching_flexions(alternative, word, True)
                if matches["is_plural"]:
                    article_alternative = ""
                elif word["genus"] == "m":
                    if match_masculine == False:
                        return None
                    article_alternative = match_masculine
                elif word["genus"] == "n":
                    if match_neuter == False:
                        return None
                    article_alternative = match_neuter
                elif word["genus"] == "f" or alternative.endswith("in"):
                    if match_feminine == False:
                        return None
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
    category,
    subcategory,
    matches,
):
    list_tokens = []

    if is_sub_category_enabled(version, config, subcategory):
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
                )
            )

    return list_tokens


def sentences_matcher(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    sentences_data,
    df_sentence,
    category,
    subcategory=None,
):
    list_tokens = []

    if not isinstance(df_sentence, list):
        if not isinstance(df_sentence, pd.DataFrame):
            return list_tokens

        df_sentence = list(df_sentence["Lemma"])

    matches = fetch_matches(tokens, df_sentence)

    if sentences_data is None:
        return sentences_matches(
            version,
            config,
            lang,
            full_text,
            tokens,
            category,
            subcategory,
            matches,
        )

    alternatives = None

    for match_id, start, end in matches:
        span = tokens[start:end]
        for sentence, *data in sentences_data:
            if span.text.lower() == sentence.lower():
                rule_subcategory = subcategory

                if len(data) == 2:
                    rule_subcategory = data[1]
                    alternatives = data[0]
                elif len(data) == 1:
                    if subcategory is None:
                        rule_subcategory = data[0]
                    else:
                        alternatives = data[0]

                if not is_sub_category_enabled(version, config, rule_subcategory):
                    continue

                list_tokens.append(
                    ResultOut.factory(
                        version,
                        config,
                        lang,
                        span.text,
                        full_text,
                        category,
                        rule_subcategory,
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
    category,
    subcategory,
    regexes,
):
    list_ending = []
    alternatives = None

    for regex in regexes:
        matches = re.finditer(regex, full_text)
        for span in matches:
            if type(span) != re.Match:
                continue

            text = span.group(1)
            explanation = None
            if len(span.groups()) == 5 and subcategory == "d_and_i":
                text = span.group(0).lstrip()
            elif len(span.groups()) == 5:
                text = span.group(0).lstrip()

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
            elif len(span.groups()) == 3:
                if span.group(3) not in rules["de-DE"]["male_articles"]:
                    continue
                if category != "inclusive":
                    alternatives = [span.group(2) + regexes[regex] + span.group(3)]
            elif len(span.groups()) == 2:
                text += span.group(2)

                if category != "inclusive":
                    alternatives = []
                    for alternative in regexes[regex]:
                        alternatives.append(span.groups()[0] + alternative)
            elif category != "inclusive":
                alternatives = regexes[regex]

            list_ending.append(
                ResultOut.factory(
                    version,
                    config,
                    lang,
                    text,
                    full_text,
                    category,
                    subcategory,
                    span.start() + 1,
                    span.end(),
                    alternatives,
                    None,
                    explanation,
                )
            )

    return list_ending


def ub_words_phrase_matcher_de(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    words_data,
    sentences_data,
    df_sentence,
    category,
):
    list_tokens = []

    for token in tokens:
        for word, word_types, alternatives, subcategory in words_data:
            if not is_sub_category_enabled(version, config, subcategory):
                continue

            if not is_word_match(token, tokens, lang, word, word_types):
                continue

            alternatives = alternatives_declension(token, lang, alternatives)

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
                    alternatives,
                )
            )

    return list_tokens + sentences_matcher(
        version,
        config,
        lang,
        full_text,
        tokens,
        sentences_data,
        df_sentence,
        category,
    )


def gendered_denom_analysis_de(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    words_data,
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
            word_types,
            alternatives_sing,
            alternatives_plur,
            subcategory,
        ) in words_data:
            if not is_sub_category_enabled(version, config, subcategory):
                continue

            word_types, lower_case, lemmatize = parse_word_types(word_types)
            if tokens[i].lemma_ == word and check_word_types(
                tokens[i], lang, word_types, True
            ):
                is_singular = is_token_singular(tokens[i], lang)
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
                        category,
                        subcategory,
                        start,
                        None,
                        alternatives,
                    )
                )

    return list_tokens


def style_word_analysis_de(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    df_sentences,
    words_data,
    sentences_data,
    false_positives,
):
    category = "style"
    list_tokens = []

    for token in tokens:
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

        for word, word_types, alternatives, subcategory in words_data:
            if not is_sub_category_enabled(version, config, subcategory):
                continue

            if not is_word_match(token, tokens, lang, word, word_types):
                continue

            alternatives = alternatives_declension(token, lang, alternatives)

            text, alternatives = detect_filler_words_at_sentence_start(
                subcategory,
                alternatives,
                token.text,
                full_text,
                token.idx + len(token.text),
            )

            list_tokens.append(
                ResultOut.factory(
                    version,
                    config,
                    lang,
                    text,
                    full_text,
                    category,
                    subcategory,
                    token.idx,
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
        sentences_data,
        df_sentences,
        category,
    )


def word_noun(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    words_data,
    category,
    matches_false=None,
):
    list_tokens = []

    for token in tokens:
        for (
            word,
            word_types,
            alternatives_sing,
            alternatives_plur,
            subcategory,
            *data,
        ) in words_data:
            if not is_sub_category_enabled(version, config, subcategory):
                continue

            if not is_word_match(token, tokens, lang, word, word_types, matches_false):
                continue

            is_singular = is_token_singular(token, lang)
            if is_singular is None:
                continue

            if is_singular:
                alternatives = alternatives_sing
            elif lang.lang == "en":
                alternatives, subcategory = plural_alternatives_en(
                    token,
                    alternatives_plur,
                    data[0],
                )

                if not is_sub_category_enabled(version, config, subcategory):
                    continue
            else:
                alternatives = alternatives_plur

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


def rules_based_words_phrase_matcher(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    category,
    words_data,
    sentences_data=None,
    df_sentence=None,
    matches_false=None,
    fallback_subcategory=None,
):
    list_tokens = []

    alternatives = None
    subcategory = fallback_subcategory

    for token in tokens:
        for word, word_types, *data in words_data:
            if not is_word_match(token, tokens, lang, word, word_types, matches_false):
                continue

            url = None
            icon = None
            explanation = None

            if len(data) > 2 and data[2] is not None:
                explanation = (
                    data[2]["text"]
                    if "text" in data[2] and data[2]["text"] != ""
                    else None
                )
                url = (
                    data[2]["url"]
                    if "url" in data[2] and data[2]["url"] != ""
                    else None
                )
                icon = (
                    data[2]["icon"]
                    if "icon" in data[2] and data[2]["icon"] != ""
                    else None
                )

            if len(data) > 1:
                subcategory = data[1]

            if lang.lang == "en":
                if len(data) > 1:
                    alternatives = alternatives_declension(token, lang, data[0])
                else:
                    subcategory = data[0]
            elif len(data) > 0:
                alternatives = alternatives_declension(token, lang, data[0])

            if not is_sub_category_enabled(version, config, subcategory):
                continue

            text, alternatives = detect_filler_words_at_sentence_start(
                subcategory,
                alternatives,
                token.text,
                full_text,
                token.idx + len(token.text),
            )

            list_tokens.append(
                ResultOut.factory(
                    version,
                    config,
                    lang,
                    text,
                    full_text,
                    category,
                    subcategory,
                    token.idx,
                    None,
                    alternatives,
                    None,
                    explanation,
                    url,
                    icon,
                )
            )

    return list_tokens + sentences_matcher(
        version,
        config,
        lang,
        full_text,
        tokens,
        sentences_data,
        df_sentence,
        category,
        fallback_subcategory,
    )


# english function to handle homonyms
def homonyms_en(
    version: float,
    config: Config,
    lang,
    full_text,
    tokens,
    matches_false,
    words_data,
):
    list_tokens = []

    for token in tokens:
        for word, word_types, category, subcategory, alternatives in words_data:
            if not is_sub_category_enabled(version, config, subcategory):
                continue

            if not is_word_match(
                token, tokens, lang, word, word_types, matches_false, False
            ):
                continue

            alternatives = alternatives_declension(token, lang, alternatives)

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
    df_sentence,
    term_list,
    lower_case=False,
):
    list_tokens = []

    matches = fetch_matches(tokens, list(df_sentence["Lemma"]))
    for match_id, start, end in matches:
        for (
            term,
            word_types,
            category,
            subcategory,
            alternatives,
            *explanation,
        ) in term_list:
            if not is_sub_category_enabled(version, config, subcategory):
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
                    category,
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
    category,
    subcategory,
):
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
                    category,
                    subcategory,
                    span.start(),
                    span.end(),
                    None,
                    None,
                    explanation,
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
