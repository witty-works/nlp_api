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
    SingularTheyType,
    Language,
    RequestIn,
    Result,
    ResultOut,
    ResultsOut,
    ResultsOut1_1,
    UserConfRequest,
    OrganizationConfRequest,
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
from app.rules import *
from app.sentry import set_up_sentry_sdk

version = "1.38.12"

settings = get_settings()
logging = set_up_logger(settings)
sentry_sdk = set_up_sentry_sdk(version, settings)
languagetool_url = get_languagetool_url(settings)
redis = set_up_redis(settings)
lang_detection = LangDetection()
initialize_aadb2c(settings)

logging.debug("app started with settings: %s", settings)

if (
    settings.slack_bot_token != None and settings.slack_signing_secret != None
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

    if lang == None:
        await respond(f"Witty could not determine a language for '{text}'.")
        return

    rules = {}

    try:
        user = await client.users_info(user=body["user_id"])
        rules = await fetch_rules_for_request(
            user_request_in, user.data["user"]["profile"]["email"]
        )
    except KeyError:
        pass

    if rules == {} and settings.slack_organization_id:
        rules = await fetch_organization_rules_for_request(
            user_request_in, settings.slack_organization_id
        )

    results = await language_rules(2.0, user_request_in.config, rules, lang, text)

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

    rules = await fetch_rules_for_request(user_request_in, user_email)

    if "authorization" in request.headers and request.headers[
        "authorization"
    ].lower().startswith("bearer"):
        claim = get_token_claims(request)
    else:
        claim = "using auth token override"

    return {
        "claim": claim,
        "rules": rules,
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

    rules = await fetch_rules_for_request(RequestIn(text=""), user_email)
    config = fetch_result_conf(rules, 1.1)
    if config == None and user_email:
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

    rules = await fetch_rules_for_request(RequestIn(text=""), user_email)
    if rules == {}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
        )

    config = fetch_result_conf(rules, 2.0)

    if "team_analytics" in rules and not rules["team_analytics"]:
        config.organization_id = None

    return config


@app.get(
    "/debug/spacy",
    include_in_schema=not settings.is_prod,
    response_class=PrettyJSONResponse,
)
async def get_debug_spacy(
    text: str,
    username: str = Depends(fetch_current_username),
):
    locale = lang_detection.get_locale(
        text,
        "auto",
        ["en", "de"],
    )

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
            }
        )

    return results


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
    results, language, limit_reached, rules, user_email = await check(
        version, request, response, user_request_in
    )

    config = fetch_result_conf(rules, version)
    if config == None and user_email:
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
    results, language, limit_reached, rules, user_email = await check(
        2.0, request, response, user_request_in
    )

    if isinstance(results, Result):
        return results

    notifications = None
    if "notifications" in rules and rules["notifications"] > 0:
        notifications = rules["notifications"]

    has_consented_to_mailing = None
    if "has_consented_to_mailing" in rules:
        has_consented_to_mailing = rules["has_consented_to_mailing"]

    return ResultsOut(
        results=results,
        language=language,
        limit_reached=limit_reached,
        config_changed=fetch_config_change(rules, user_request_in),
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
    results, language, limit_reached, rules, user_email = await check(
        2.1, request, response, user_request_in
    )

    if isinstance(results, Result):
        return results

    notifications = None
    if "notifications" in rules and rules["notifications"] > 0:
        notifications = rules["notifications"]

    has_consented_to_mailing = None
    if "has_consented_to_mailing" in rules:
        has_consented_to_mailing = rules["has_consented_to_mailing"]

    return ResultsOut(
        results=results,
        language=language,
        limit_reached=limit_reached,
        config_changed=fetch_config_change(rules, user_request_in),
        notifications=notifications,
        has_consented_to_mailing=has_consented_to_mailing,
    )


# data exchange routes
@app.post("/organization/rules")
async def post_organization_rules(
    organization_rules: OrganizationConfRequest,
    username: str = Depends(fetch_current_username),
):
    redis.set(organization_rules.id, organization_rules.json())

    return organization_rules


@app.delete(
    "/organization/rules",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_organiztion_rules(
    organization_id: str,
    username: str = Depends(fetch_current_username),
):
    redis.delete(organization_id)


@app.get(
    "/organization/rules", response_model=dict, responses={404: {"model": ErrorMessage}}
)
async def get_organization_rules(
    organization_id: str,
    username: str = Depends(fetch_current_username),
):
    return await fetch_organization_rules_from_redis(organization_id)


@app.post("/user/rules")
async def post_user_rules(
    user_rules: UserConfRequest, username: str = Depends(fetch_current_username)
):
    redis.set(user_rules.email, user_rules.json())

    return user_rules


@app.delete(
    "/user/rules",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_user_rules(
    email: str,
    username: str = Depends(fetch_current_username),
):
    redis.delete(email)


@app.get("/user/rules", response_model=dict, responses={404: {"model": ErrorMessage}})
async def get_user_rules(
    email: str,
    username: str = Depends(fetch_current_username),
):
    rules = await fetch_user_organization_rules(email)

    if not rules or type(rules) is not dict:
        return JSONResponse(
            status_code=404, content={"message": "User rules not found"}
        )

    return rules


# Functions
async def fetch_organization_rules_from_redis(
    organization_id: str,
):
    rules = redis.get(organization_id)
    if not rules:
        raise HTTPException(status_code=404, detail="Organization rules not found")

    return json.loads(rules)


async def fetch_user_rules_from_redis(
    email: str,
):
    rules = redis.get(email)
    if not rules:
        raise HTTPException(status_code=404, detail="User rules not found")

    return json.loads(rules)


async def fetch_user_organization_rules(email: str):
    try:
        rules = await fetch_user_rules_from_redis(email)
    except HTTPException:
        return None

    rules["plan"] = "witty_free"
    rules["organization_name"] = None
    rules["organization_config_hash"] = None
    rules["organization_domains"] = None

    if "organization_id" in rules and rules["organization_id"] != None:
        try:
            organization_rules = await fetch_organization_rules_from_redis(
                rules["organization_id"]
            )

            rules["plan"] = organization_rules["plan"]
            rules["organization_name"] = organization_rules["name"]

            if "config_hash" in organization_rules:
                rules["organization_config_hash"] = organization_rules["config_hash"]
            else:
                rules["organization_config_hash"] = None

            if "domains" in organization_rules:
                rules["organization_domains"] = organization_rules["domains"]
            else:
                rules["organization_domains"] = {}

            rules["organization_config"] = organization_rules["config"]
            rules["organization_term_replacements"] = organization_rules[
                "term_replacements"
            ]
            rules["organization_false_positives"] = organization_rules[
                "false_positives"
            ]
        except HTTPException:
            pass
    else:
        rules["organization_id"] = None

    return rules


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


def apply_rules(user_request_in: RequestIn, configs: dict, plan: str):
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


async def fetch_rules_for_request(user_request_in: RequestIn, user_email=Optional[str]):
    user_request_in.config.__setattr__("store_context", True)
    user_request_in.config.__setattr__("plan", None)

    if not user_email:
        return {}

    rules = await fetch_user_organization_rules(user_email)
    if not rules or type(rules) is not dict:
        return {}

    apply_rules(user_request_in, rules["config"], rules["plan"])

    if "organization_config" in rules:
        apply_rules(user_request_in, rules["organization_config"], rules["plan"])

        rules["term_replacements"] |= rules["organization_term_replacements"]
        rules["false_positives"] = list(
            set(rules["false_positives"] + rules["organization_false_positives"])
        )

    if rules["plan"] != "witty_teams":
        user_request_in.config.maximum_importance = min(
            2.0, user_request_in.config.maximum_importance
        )

    return rules


async def fetch_organization_rules_for_request(
    user_request_in: RequestIn, organization_id=Optional[str]
):
    user_request_in.config.__setattr__("store_context", True)

    if not organization_id:
        return {}

    try:
        rules = await fetch_organization_rules_from_redis(organization_id)
    except HTTPException:
        return {}

    for config in rules["configs"]:
        if rules["configs"][config]["status"] == "suggestion":
            rules["configs"][config]["status"] = "force"

    apply_rules(user_request_in, rules["config"], rules["plan"])

    return rules


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

    if locale == None:
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

    rules = await fetch_rules_for_request(user_request_in, user_email)

    text, lang, limit_reached = fetch_text(user_request_in)

    if lang == None:
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        results = Result.factory("Language could not be determined")
        language = None
        rules = {}
    else:
        results = await language_rules(
            version, user_request_in.config, rules, lang, text
        )

        language = lang.lang

    return results, language, limit_reached, rules, user_email


def fetch_config_change(
    rules: dict,
    user_request_in: Optional[RequestIn] = None,
):
    if not user_request_in:
        return True

    if "config_hash" in rules and user_request_in.config_hash != rules["config_hash"]:
        return True

    if (
        "organization_config_hash" in rules
        and user_request_in.organization_config_hash
        != rules["organization_config_hash"]
    ):
        return True

    return None


def fetch_result_conf(
    rules: dict,
    version: float,
):
    if "config" not in rules:
        return None

    if "organization_config" in rules:
        organization_config = RuleConfig.parse_obj(rules["organization_config"])
    else:
        organization_config = None

    plan = rules["plan"]

    if version < 2.0:
        return ResultConf1_1(
            id=rules["organization_id"],
            name=rules["organization_name"],
            plan=plan,
            config=organization_config,
        )

    config = RuleConfig.parse_obj(rules["config"])

    return ResultConf(
        id=rules["id"],
        name=rules["name"],
        plan=plan,
        config=config,
        organization_id=rules["organization_id"],
        organization_name=rules["organization_name"],
        organization_config=organization_config,
        domains=rules["domains"],
        organization_domains=rules["organization_domains"],
        config_hash=rules["config_hash"],
        organization_config_hash=rules["organization_config_hash"],
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
            and text[start + 1 : end] in male_articles
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

        if category != "style":
            anchor = (
                label.lower()
                .replace(" ", "_")
                .replace("ß", "ss")
                .replace("ü", "ue")
                .replace("ä", "ae")
                .replace("ö", "oe")
            )
        else:
            anchor = None

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
                anchor,
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

        if config.simple_language and payload["language"] == "de-DE":
            payload["language"] += "-x-simple-language"

        if config.primary_language != None:
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
    if list_false_positive == None:
        return False

    for match_id, start, end in list_false_positive:
        span_false = tokens[start:end]
        if token.idx in range(span_false.start_char, span_false.end_char):
            return True

    return False


# create false positives patterns based on false positives column
def false_pattern_match(tokens, lang):
    matcher = Matcher(model[lang.lang].vocab)

    for false_positive in pattern_false_positives[lang.lang]:
        matcher.add("FalsePositivesList", false_positive)

    return matcher(tokens)


def fetch_false_positive_matcher(tokens, lang):
    # create false positives list
    phrase_matches_false = fetch_matches(tokens, list_false_column)
    word_matches_false = false_pattern_match(tokens, lang)
    return list(set(phrase_matches_false + word_matches_false))


def fetch_matches(tokens, phrases):
    # Phrase matcher part to handle False positives with two words and special symbols
    matcher = PhraseMatcher(model[lang.lang].vocab, attr="LOWER")

    # Only run model.make_doc to speed things up
    patterns = [model[lang.lang].make_doc(text) for text in phrases]
    matcher.add("TerminologyList", patterns)
    return matcher(tokens)


async def language_rules(
    version: float, config: Config, rules: dict, lang: Language, text: str
):
    tokens = fetch_tokens(lang, text)

    list_results = []
    if is_sub_category_enabled(
        version, config, "orthography"
    ) or is_sub_category_enabled(version, config, "style"):
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

    if "term_replacements" in rules:
        term_replacements = {
            "Lemma": [],
            "Word_Type": [],
            "Category": [],
            "Primary_subcategory": [],
            "Alt_split": [],
            "Explanation": [],
        }

        for term in rules["term_replacements"]:
            term_replacement = rules["term_replacements"][term]

            term_replacements["Lemma"].append(term)
            term_replacements["Word_Type"].append("")
            term_replacements["Category"].append("corporate_rules")
            term_replacements["Primary_subcategory"].append("corporate_rules")
            term_replacements["Alt_split"].append(term_replacement["alternatives"])
            term_replacements["Explanation"].append(term_replacement["explanation"])

        df_term_replacements = pd.DataFrame(data=term_replacements)
        alternatives = list(
            zip(
                df_term_replacements["Lemma"],
                df_term_replacements["Word_Type"],
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
    if "false_positives" in rules:
        false_positives = rules["false_positives"]

    if "term_replacements" in rules:
        for rule in rules["term_replacements"]:
            false_positives.append(rules["term_replacements"][rule]["alternatives"][0])

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
            abbreviation,
            True,
        )

    if is_sub_category_enabled(version, config, "openly_discriminating"):
        list_full += rules_based_words_phrase_matcher(
            version,
            config,
            lang,
            text,
            tokens,
            open_disc_words_data,
            open_disc_sentences_data,
            rules["de-DE"]["df_open_dis_sentence"],
            "openly_discriminating",
        )

    if is_sub_category_enabled(version, config, "gendered"):
        list_full += (
            rules_based_words_phrase_matcher(
                version,
                config,
                lang,
                text,
                tokens,
                gender_words_data_no_noun,
                gender_sentences_data,
                rules["de-DE"]["df_gendered_sentences"],
                "gendered",
            )
            + gendered_denom_analysis_de(
                version,
                config,
                lang,
                text,
                tokens,
                gender_words_data,
                false_positives.gender,
            )
            + regex_matches(
                version,
                config,
                lang,
                text,
                categories["gendered"]["category"],
                "gender_specific_abbreviation",
                m_w_regexes,
            )
        )

    if is_sub_category_enabled(
        version, config, "gendered_denominations_ending"
    ) and ResultOut.genderedRolesFormatInclusive(config.gendered_roles_format):
        subcategory = "gendered_denominations_ending"
        category = categories[subcategory]["category"]
        regexes = {}
        for ending, regex in config._gendereddenom_ending.items():
            if config.german_gender_ending == ending:
                continue

            regexes[regex] = [config.german_gender_ending]

            if ending == ":in":
                regexes["\s((\S+):(\S+))"] = config.german_gender_ending[0:1]
            elif ending == "*in":
                regexes["\s((\S+)\*(\S+))"] = config.german_gender_ending[0:1]

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
            bias_words_data_no_plur,
            bias_sentences_data,
            rules["de-DE"]["df_ub_sentences"],
            "unconscious_bias",
        ) + word_noun(
            version,
            config,
            lang,
            text,
            tokens,
            bias_words_data_noun,
            "unconscious_bias",
        )

    if is_sub_category_enabled(version, config, "communal"):
        list_full += rules_based_words_phrase_matcher(
            version,
            config,
            lang,
            text,
            tokens,
            rules["de-DE"]["df_communal_words"],
            None,
            [],
            "inclusive",
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
            rules["de-DE"]["df_d_and_i_words"],
            None,
            rules["de-DE"]["df_terms_d_and_i_words"],
            "inclusive",
            [],
            "d_and_i",
        )

        subcategory = "d_and_i"
        category = categories[subcategory]["category"]
        regexes = {config._gendereddenom_ending[config.german_gender_ending]: None}
        if config.german_gender_ending == ":in":
            regexes["\s((\S+):(\S+))"] = None
        elif ending == "*in":
            regexes["\s((\S+)\*(\S+))"] = None

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
            style_words_data,
            style_sentences_data,
            false_positives.style,
        )

    return list_full


# Function for all English rules
def english_rules(version: float, config: Config, lang: Language, tokens, text: str):
    list_full = []

    words_data_en = defaultdict(list)
    inclusive_words_data_en = []
    gendered_words_data_en = defaultdict(list)
    inclusive_sentences_data_en = []
    sentences_data_en = defaultdict(list)
    matches_false = fetch_false_positive_matcher(tokens, lang)

    if lang.locale == "en-GB":
        words_data_en["od"] = open_disc_words_data_GB
        words_data_en["ge"] = gender_words_data_GB
        words_data_en["ge-singular-they"] = (
            gender_words_data_GB + bias_singular_they_alternatives_GB
        )
        words_data_en["style"] = style_words_data_GB
        words_data_en["bias"] = bias_words_data_GB
        words_data_en["homonym"] = homonyms_word_GB
        words_data_en["abbr"] = abbreviation_GB

        inclusive_words_data_en = inclusive_words_data_GB
        gendered_words_data_en["gendered"] = gender_noun_words_data_GB
        gendered_words_data_en["bias"] = gender_bias_words_data_GB
        inclusive_sentences_data_en = inclusive_sentences_data_GB
        sentences_data_en["od"] = open_dis_sentences_GB
        sentences_data_en["ge"] = gender_sentences_data_GB
        sentences_data_en["style"] = style_sentences_data_GB
        sentences_data_en["bias"] = bias_sentences_data_GB
    else:
        words_data_en["od"] = open_disc_words_data_US
        words_data_en["ge"] = gender_words_data_US
        words_data_en["ge-singular-they"] = (
            gender_words_data_US + bias_singular_they_alternatives_US
        )
        words_data_en["style"] = style_words_data_US
        words_data_en["bias"] = bias_words_data_US
        words_data_en["homonym"] = homonyms_word_US
        words_data_en["abbr"] = abbreviation_US

        inclusive_words_data_en = inclusive_words_data_US
        gendered_words_data_en["gendered"] = gender_noun_words_data_US
        gendered_words_data_en["bias"] = gender_bias_words_data_US
        inclusive_sentences_data_en = inclusive_sentences_data_US
        sentences_data_en["od"] = open_dis_sentences_US
        sentences_data_en["ge"] = gender_sentences_data_US
        sentences_data_en["style"] = style_sentences_data_US
        sentences_data_en["bias"] = bias_sentences_data_US

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
            words_data_en["od"],
            sentences_data_en["od"],
            rules[lang.locale]["df_open_dis_sentence"],
            "openly_discriminating",
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
                words_data_en["ge-singular-they"],
                sentences_data_en["ge"],
                rules[lang.locale]["df_gendered_sentence"],
                "gendered",
                matches_false,
            )
        else:
            list_full += rules_based_words_phrase_matcher(
                version,
                config,
                lang,
                text,
                tokens,
                words_data_en["ge"],
                sentences_data_en["ge"],
                rules[lang.locale]["df_gendered_sentence"],
                "gendered",
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
            m_w_regexes,
        )

    if is_sub_category_enabled(version, config, "inclusive"):
        list_full += rules_based_words_phrase_matcher(
            version,
            config,
            lang,
            text,
            tokens,
            inclusive_words_data_en,
            inclusive_sentences_data_en,
            rules[lang.locale]["df_inclusive_sentence"],
            "inclusive",
            matches_false,
        )

    if is_sub_category_enabled(version, config, "style"):
        list_full += rules_based_words_phrase_matcher(
            version,
            config,
            lang,
            text,
            tokens,
            words_data_en["style"],
            sentences_data_en["style"],
            rules[lang.locale]["df_style_sentence"],
            "style",
            matches_false,
        )

    if is_sub_category_enabled(version, config, "unconscious_bias"):
        list_full += rules_based_words_phrase_matcher(
            version,
            config,
            lang,
            text,
            tokens,
            words_data_en["bias"],
            sentences_data_en["bias"],
            rules[lang.locale]["df_ub_sentence"],
            "unconscious_bias",
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

    if word_types == None:
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

    if token.pos_ == "PROPN" and single_word != None and len(word_types):
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


def determine_genus_from_ending(word, endings, genus):
    for ending in endings:
        if word.endswith(ending):
            return {"genus": genus}

    return None


def german_noun_analysis(word):
    if "..." in word:
        return None

    result = german_nouns[word]
    if len(result):
        result = result[0]
    else:
        for genus in primary_german_genus_endings:
            result = determine_genus_from_ending(
                word, primary_german_genus_endings[genus], genus
            )

            if result != None:
                return result

        # skip the first 2 letters
        i = 2
        # skip the last 4 letters, especially to avoid cases like 'Ende' at the end of 'Arbeitgebende'
        while i < len(word) - 4:
            partial_word = word[i:].capitalize()
            i += 1

            result = german_nouns[partial_word]
            if len(result):
                result = result[0]
                break

    if result == []:
        result = None

    if result == None:
        for genus in secondary_german_genus_endings:
            result = determine_genus_from_ending(
                word, secondary_german_genus_endings[genus], genus
            )

            if result != None:
                return result

    if isinstance(result, list) and "genus 1" in result:
        result["genus"] = result["genus 1"]

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
        if a_word == None:
            return b_text

        b_word = german_noun_analysis(b_text)
        if b_word == None:
            return b_text

        for flexion, value in a_word["flexion"].items():
            if value != a_text:
                continue

            if flexion not in b_word["flexion"]:
                flexion += " 1"

            if flexion in b_word["flexion"]:
                return b_word["flexion"][flexion]

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
    if text == token.lemma_ or not text.startswith(token.lemma_):
        return alternative

    if ResultOut.isInspirationAlternative(text, alternative):
        return alternative

    new_alternative = ""
    previous = False
    tokens = fetch_tokens(lang, alternative)
    for alternative_token in reversed(tokens):
        alternative_text = alternative_token.text
        if alternative_text in conjunctions[lang.lang]:
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

    if token_morph_number[0] == "Plur":
        return [
            item for item in alternative_plur if item != token.text.lower()
        ], second_subcategory

    return None


def plural_or_singular_alternatives_de(
    token_morph_number, alternative_sing, alternative_plur
):
    if token_morph_number[0] == "Sing":
        return alternative_sing

    if token_morph_number[0] == "Plur":
        return alternative_plur

    return None


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
    if word == None:
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
    for form, masculine, feminine, neuter, plural, alternative in articles:
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
            if matched_form == None:
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

    if match_alternative == None:
        return None

    alternatives_with_article = []
    for alternative in alternatives:
        if "~" in alternative:
            article_alternative = match_alternative
        else:
            if "---" in alternative:
                alternative, alternative_context = ResultOut.parse_alternative_context(
                    alternative
                )

            words = alternative.split()
            word = german_noun_analysis(words[-1])
            if word == None:
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
                    [],
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
    if not isinstance(df_sentence, list):
        df_sentence = list(df_sentence["Lemma"])

    matches = fetch_matches(tokens, df_sentence)

    if sentences_data == None:
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

    list_tokens = []
    alternatives = None

    for match_id, start, end in matches:
        span = tokens[start:end]
        for sentence, *data in sentences_data:
            if span.text.lower() == sentence.lower():
                if len(data) >= 1:
                    if len(data) >= 2:
                        subcategory = data[1]

                    if subcategory == None:
                        subcategory = data[0]
                    else:
                        alternatives = data[0]

                if not is_sub_category_enabled(version, config, subcategory):
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

            groups = span.groups()
            text = span.group(1)

            if len(groups) == 3:
                if span.group(3) not in male_articles:
                    continue
                text = span.group(1)
                if category != "inclusive":
                    alternatives = [span.group(2) + regexes[regex] + span.group(3)]
            elif len(groups) == 2:
                text += span.group(2)

                if category != "inclusive":
                    alternatives = []
                    for alternative in regexes[regex]:
                        alternatives.append(groups[0] + alternative)
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
                    span.start() + 1,  # remove extra \s character
                    span.end(),
                    alternatives,
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
            alternatives_all,
            subcategory,
        ) in words_data:
            if not is_sub_category_enabled(version, config, subcategory):
                continue

            word_types, lower_case, lemmatize = parse_word_types(word_types)
            if tokens[i].lemma_ == word and check_word_types(
                tokens[i], lang, word_types, True
            ):
                token_morph_number = tokens[i].morph.get("Number")
                if is_number_list_empty(token_morph_number, tokens[i], full_text):
                    alternatives = alternatives_all
                else:
                    alternatives = plural_or_singular_alternatives_de(
                        token_morph_number, alternatives_sing, alternatives_plur
                    )

                if alternatives == None:
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

                if (
                    i > 0
                    and len(token_morph_number)
                    and token_morph_number[0] == "Sing"
                ):
                    alternatives_with_article = fetch_alternatives_with_article(
                        tokens, i, alternatives
                    )
                    if alternatives_with_article != None:
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
                re.search(r"^ *$", preceeding_text) != None
                or re.search(r"[.!?:,]\s*$", preceeding_text, re.MULTILINE) != None
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

            token_morph_number = token.morph.get("Number")
            if is_number_list_empty(token_morph_number, token, full_text):
                continue

            if lang.lang == "en":
                alternatives, subcategory = plural_or_singular_en(
                    token,
                    token_morph_number,
                    alternatives_sing,
                    alternatives_plur,
                    subcategory,
                    data[0],
                )

                if not is_sub_category_enabled(version, config, subcategory):
                    continue
            else:
                alternatives = plural_or_singular_alternatives_de(
                    token_morph_number, alternatives_sing, alternatives_plur
                )

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


def detect_filler_words_at_sentence_start(subcategory, alternatives, text, full_text, end):
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
    words_data,
    sentences_data,
    df_sentence,
    category,
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
                )
            )

    list_tokens += sentences_matcher(
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

    return list_tokens


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
                    alternatives,
                    None,
                    explanation_text,
                    url,
                    icon,
                )
            )

    return list_tokens


# want to server to run app.py in the folder app as main app, port=8000 is defaut port for the fast api
# reload=True is debag mode in Flask is on, to set =False, when deploy the app to the production
# might be added host="0.0.0.0"
if __name__ == "__main__":  # pragma: no cover
    # If this is being ran directly as a script, run an internal uvicorn server
    # to service API requests
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level=settings.logging_config_level)
