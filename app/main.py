import re
import uvicorn
import json
import secrets
import aiohttp
from typing import Optional, Union, List
from collections import defaultdict, namedtuple
import os
import fasttext

from spacy.matcher import PhraseMatcher, Matcher
from spacy import displacy

from inflex import Noun, Verb, Adjective

from fastapi import (
    FastAPI,
    Request,
    Response,
    HTTPException,
    Depends,
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
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import RedirectResponse

from app.auth_service import (
    validate_scope,
    get_token_claims,
    decode_B2C_JWT,
    decode_JWT,
)

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
    Client,
    Config,
    GenderedRolesFormatType,
    GermanGenderEndingType,
    RuleType,
    LangType,
    Language,
    BaseRequestIn,
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
    RuleIn,
)
from app.lang_detection import get_lang_detection
from app.categories import (
    get_category_keys,
    get_categories,
    get_category,
    add_advanced,
)
from app.settings import get_settings
from app.logger import set_up_logger
from app.redis_setup import set_up_redis
from app.model import fetch_nlp_model
from app.rules import fetch_rules, Rule
from app.sentry import set_up_sentry_sdk
from app.model import lemma_plural_lookup

version = "1.49.3"

categories = get_categories()
settings = get_settings()
logging = set_up_logger(settings)
sentry_sdk = set_up_sentry_sdk(version, settings)
redis = set_up_redis(settings)

logging.debug("app started with settings: %s", settings)

model = {}
for spacy_model in settings.models:
    lang = spacy_model[0:2]
    model[lang] = fetch_nlp_model(lang, spacy_model)

rules = fetch_rules(model)

# https://www.notion.so/witty-works/Rule-Guidelines-432792da944141b1b4d0a01de290aa43#aac0d966bfeb4e33a5a346bba45d5ea8
supported_word_types = {"n", "a", "adv", "v", "conj"}

if settings.fasttext:
    pretrained_lang_model = os.getcwd() + "/training_data/lid.176.bin"
    fasttext_model = fasttext.load_model(pretrained_lang_model)

if settings.slack_bot_token and settings.slack_signing_secret:  # pragma: no cover
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

    user_request_in = RequestIn(client="slack:1.0.0", text=body["text"])
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
            user_request_in, settings.slack_organization_id
        )

    user_request_in.config.__setattr__("alternatives_max_count", None)
    client = parse_client(user_request_in.client)
    results = await apply_language_rules(
        version, client, user_request_in.config, configs, lang, text
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
hsts = secure.StrictTransportSecurity().include_subdomains().preload().max_age(31536000)
referrer = secure.ReferrerPolicy().no_referrer()
cache_value = secure.CacheControl().no_cache()
xfo = secure.XFrameOptions().deny()

secure_headers = secure.Secure(
    csp=csp,
    hsts=hsts,
    referrer=referrer,
    cache=cache_value,
    xfo=xfo,
)


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
    if not settings.api_docs_username or not settings.api_docs_password:
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
        except Exception:
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
    if not settings.is_prod and settings.testing is False:  # pragma: no cover
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
        if "v2.0" not in path:
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

    german_gender_endings = Config._gendereddenom_ending.default.keys()
    if german_gender_ending is not None:
        german_gender_endings = [german_gender_ending]

    for german_gender_ending in german_gender_endings:
        if german_gender_ending not in Config._gendereddenom_ending_article.default:
            continue

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
async def post_auth_2_0(request: Request, user_request_in: BaseRequestIn = None):
    client = parse_client(
        user_request_in.client if user_request_in is not None else None
    )
    check_client_version(client)

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
    # BC code for browser version before 1.29.0
    old_categories = ["style", "inclusive", "orthography"]
    for old_category in old_categories:
        if old_category in config:
            continue

        if old_category in config["categories"]:
            config[old_category] = config["categories"][old_category]
        else:
            config[old_category] = {
                "value": False,
                "status": "suggestion",
            }

    return config


@app.post(
    "/debug/rule",
    include_in_schema=not settings.is_prod,
    response_model=List[ResultOut],
    response_model_exclude_none=True,
)
async def post_debug_rule(
    rule_data: RuleIn,
    username: str = Depends(fetch_current_username),
):
    lang = Language(rule_data.lang)
    config = Config(plan="witty_teams")

    tokens = fetch_tokens(lang.lang, rule_data.text)
    offsets = utf16_offsets(rule_data.text)
    false_positive_matcher = fetch_false_positive_matchers(lang.lang, tokens)

    if rule_data.alternatives is not None:
        alternative_list = []
        for alternative in rule_data.alternatives:
            alternative = alternative.lemma.strip() + (
                "" if alternative.label is None else " --- " + alternative.label
            )
            alternative_list.append(alternative)
    else:
        alternative_list = None

    rules = []
    for subcategory in rule_data.subcategories:
        if subcategory.endswith("_advanced"):
            subcategory = "advanced_" + subcategory.removesuffix("_advanced")

        rule = Rule(
            "test",
            rule_data.lang,
            rule_data.lemma,
            tokenize(rule_data.lemma, rule_data.lang),
            rule_data.word_types,
            subcategory,
        )

        rule.alternatives = alternative_list
        rule.false_positives = rule_data.false_positives

        rules.append(rule)

    list_full = []
    client = parse_client("debug:" + version)

    i = 0
    token_count = len(tokens)
    while i < token_count:
        for rule in rules:
            rule_check(
                version,
                config,
                client,
                lang,
                rule_data.text,
                i,
                tokens,
                offsets,
                list_full,
                [rule],
                false_positive_matcher,
                rule_data.lower_case,
            )

        i += 1

    return list_full


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
    results = []
    tokens = fetch_tokens(lang, text)
    word_type_rule = None
    for token in tokens:
        if word_type_rule is None:
            word_type_rule = ""
        else:
            word_type_rule += "|"

        word_type = fetch_word_type(lang, token)
        if token.text != token.lemma_:
            word_type_rule += "~"
        word_type_rule += word_type

        results.append(
            {
                "text": token.text,
                "lemma": token.lemma_,
                "ner": token.ent_type_,
                "start": token.idx,
                "tag": token.tag_,
                "pos": token.pos_,
                "dep": token.dep_,
                "word_type": word_type,
                "morph": token.morph.to_dict(),
                "is_emoji": token._.is_emoji,
                "is_singular": is_token_singular(lang, token),
                "emoji_desc": token._.emoji_desc,
                "whitespace": token.whitespace_,
            }
        )

    return [{"word_type": word_type_rule}] + results


@app.get(
    "/debug/displacy",
    include_in_schema=not settings.is_prod,
)
async def get_debug_spacy(
    text: str,
    lang: LangType,
    username: str = Depends(fetch_current_username),
):
    tokens = fetch_tokens(lang, text)

    sentence_spans = list(tokens.sents)
    data = displacy.render(sentence_spans, style="dep")
    return Response(content=data, media_type="application/xml")


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


@app.get("/lemmatize")
async def get_lemmatize(
    text: str,
    lang: LangType,
    all: bool = False,
    username: str = Depends(fetch_current_username),
):
    tokens = fetch_tokens(lang, text)
    if all:
        return tuple([i.lemma_ for i in tokens])

    if len(tokens) != 1:
        return None

    return tokens[0].lemma_


@app.get("/tokenize")
async def get_tokenize(
    text: str,
    lang: LangType,
    username: str = Depends(fetch_current_username),
):
    return tokenize(text, lang)


@app.get("/parse-word-types")
async def get_tokenize(
    text: str,
    word_types: str,
    lang: LangType,
    username: str = Depends(fetch_current_username),
):
    tokens = fetch_tokens(lang, text)
    word_type_list = word_types.split("|")

    if len(tokens) != len(word_type_list):
        raise RequestValidationError(
            f"Word type '{word_types}' count does not match text token count '{len(tokens)}' for text '{text}'."
        )

    parsed_word_types = []
    for word_type in word_type_list:
        parsed_word_type, lower_case, lemmatize = parse_word_type(word_type)

        if parsed_word_type != "" and parsed_word_type not in supported_word_types:
            raise RequestValidationError(
                f"Word type '{word_type}' within '{word_types}' contains unsupported word type '{parsed_word_type}'"
            )

        parsed_word_types.append(
            {
                "word_type": parsed_word_type,
                "lower_case": lower_case,
                "lemmatize": lemmatize,
            }
        )

    return parsed_word_types


@app.post(
    "/organization/configs",
    response_model=ConfResponse,
    response_model_exclude_none=True,
)
async def post_organization_configs(
    organization_configs: OrganizationConfRequest,
    username: str = Depends(fetch_current_username),
):
    redis.set(organization_configs.id, organization_configs.model_dump_json())

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
    redis.set(user_configs.email.lower(), user_configs.model_dump_json())

    return user_configs


@app.delete(
    "/user/configs",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_user_configs(
    email: str,
    username: str = Depends(fetch_current_username),
):
    redis.delete(email.lower())


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
    configs = redis.get(email.lower())
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

            configs["organization_config_hash"] = (
                organization_configs["config_hash"]
                if "config_hash" in organization_configs
                else None
            )

            configs["organization_domains"] = (
                organization_configs["domains"]
                if "domains" in organization_configs
                else {}
            )

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
    if token.text in lemma_plural_lookup[lang]:
        return False

    number = token.morph.get("Number")
    if number:
        return "Sing" in number

    if lang == "en" and token.pos == "NOUN" and token.text.endswith("s"):
        return False

    return None


def is_token_plural(lang, token):
    is_singular = is_token_singular(lang, token)
    if is_singular is None:
        return None

    return not is_singular


def apply_configs(
    user_request_in: RequestIn, configs: dict, plan: str, force_disables: bool = True
):
    disabled_categories = user_request_in.config.disabled_categories

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
                elif force_disables and category not in disabled_categories:
                    disabled_categories.append(category)
        elif config == "store_context":
            if (
                plan is not None
                and plan != "witty_free"
                and data["status"] == "force"
                and not data["value"]
            ):
                user_request_in.config.__setattr__("store_context", False)
        elif data["status"] == "force":
            user_request_in.config.__setattr__(config, data["value"])

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
        # debug
        if version is None:
            user_request_in.config.__setattr__(
                "disabled_categories", ["advanced_plain_language"]
            )
        else:
            user_request_in.config.__setattr__(
                "disabled_categories", get_category_keys(True)
            )

        return {}

    try:
        configs = await fetch_user_organization_configs(user_email)
    except HTTPException:
        configs = None

    if not configs or type(configs) is not dict:
        return {}

    apply_configs(user_request_in, configs["config"], configs["plan"])

    if "organization_config" in configs:
        apply_configs(
            user_request_in,
            configs["organization_config"],
            configs["plan"],
            False,
        )

        configs["term_replacements"] |= configs["organization_term_replacements"]
        configs["false_positives"] = list(
            set(configs["false_positives"] + configs["organization_false_positives"])
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
        if "email" in claims:
            return claims["email"]

        if "emails" in claims and len(claims["emails"]) > 0:
            return claims["emails"][0]

        # Office SSO
        if "preferred_username" in claims:
            return claims["preferred_username"]
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
            unverified_claims = get_token_claims(request)
            for key in settings.sso_configs:
                config = settings.sso_configs[key]
                if (
                    "aud" not in unverified_claims
                    or unverified_claims["aud"] != config["client_id"]
                ):
                    continue

                if "domain" in config:
                    decode_B2C_JWT(
                        request,
                        config["rsa_key"],
                        config["tenant_id"],
                        config["client_id"],
                        config["domain"],
                    )
                else:
                    decode_JWT(
                        request,
                        config["rsa_key"],
                        config["tenant_id"],
                        config["client_id"],
                    )
                validate_scope(settings.aadb2c_expected_scope, request)
                claims = get_token_claims(request)
                return fetch_email_from_claims(claims)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=str(e.args[0])
            )

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token provided did not map to a valid client ID",
        )

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

    lang = None if locale is None else Language(locale)

    return text, lang, limit_reached


def check_api_version(version: float):
    if version != 2.3:  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"API version '{version}' not supported, please use version '2.3'.",
        )


def check_client_version(client: Client):
    if client.name in settings.minimum_versions and client.version < VersionString(
        settings.minimum_versions[client.name]
    ):  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Client version '{client.version}' not supported, please use at least '{settings.minimum_versions[client.name]}'.",
        )


async def check(
    request: Request,
    response: Response,
    user_request_in: RequestIn,
    version: Optional[float],
):
    client = parse_client(user_request_in.client)
    check_client_version(client)

    if version is not None:
        check_api_version(version)

        user_email = fetch_user(request)
        configs = await fetch_configs_for_request(version, user_request_in, user_email)
    else:
        # debug
        version = 2.3
        configs = {"categories": {}}
        apply_configs(user_request_in, configs, "witty_teams")

    text, lang, limit_reached = fetch_text(user_request_in)

    if lang is None:
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        results = Result.factory("Language could not be determined")
        language = None
        configs = {}
    else:
        results = await apply_language_rules(
            version, client, user_request_in.config, configs, lang, text
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

    organization_config = (
        RuleConfig.model_validate(configs["organization_config"])
        if "organization_config" in configs
        else None
    )

    plan = configs["plan"]

    config = RuleConfig.model_validate(configs["config"])

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
    version: float,
    config: Config,
    client: Client,
    lang: Language,
    full_text: str,
    tokens,
    offsets,
    result,
):
    if (
        not isinstance(result, dict)
        or "matches" not in result
        or len(result["matches"]) == 0
    ):
        return []

    entities = []
    for ent in tokens.ents:
        entities.append(ent)

    list_results = []
    ignore = ["@", "#"]

    gendered_denom = lang.lang == "de" and ResultOut.genderedRolesFormatInclusive(
        config.gendered_roles_format
    )

    for match in result["matches"]:
        start = int(match["offset"])
        end = start + int(match["length"])

        if offsets and start in offsets["utf16_chars"]:
            start = offsets["utf16_chars"][start]

        if offsets and end in offsets["utf16_chars"]:
            end = offsets["utf16_chars"][end]

        text = full_text[start:end]

        # Ignore case issues at the start of sentence due to chunking issues
        # https://github.com/witty-works/browser-extension/pull/880
        if match["rule"]["id"] == "DE_CASE":
            preceeding_text = full_text[start - 10 : start]
            preceeding_text = preceeding_text.rstrip(" ")
            # check if before the word there is only spaces and a newline or tab
            if len(preceeding_text) and preceeding_text[-1] in ["\n", "\t"]:
                continue

        if match["rule"]["id"] == "WHITESPACE_RULE" and (
            start == 0 or full_text[0:end].isspace()
        ):
            continue

        # Ignore typos on names
        if match["rule"]["category"]["id"] == "TYPOS" and text[0:1].isupper():
            is_entity = False
            for entity in entities:
                if (
                    entity.start_char >= start
                    and entity.start_char < end
                    and entity.end_char >= end
                ) or (
                    entity.start_char <= start
                    and entity.end_char > start
                    and entity.end_char <= end
                ):
                    is_entity = entity.label_ in rules["named_entity_labels"]["names"]
                    break

            if is_entity:
                continue

        # Ignore capitalization after salutation
        # Todo: Train NER to handle salutations better like "\n Hallo Konstantina\n\nWie geht es dir?"
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
                client,
                lang,
                text,
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


def convert_to_csv(payload, key):
    if len(payload[key]):
        payload[key] = ",".join(payload[key])
    else:
        del payload[key]

    return payload


async def apply_languagetool_rules(
    version: float,
    config: Config,
    client: Client,
    lang: Language,
    text: str,
    tokens,
    offsets,
):
    if not settings.languagetool_api:
        return []

    payload = {
        "text": text,
        "language": lang.locale,
        "disabledCategories": ["GENDER_NEUTRALITY", "COLLOQUIALISMS"],
        "enabledCategories": [],
        # Ignore case issues at the start of sentence due to chunking issues
        # https://github.com/witty-works/browser-extension/pull/880
        "disabledRules": ["UPPERCASE_SENTENCE_START"],
    }

    if is_sub_category_enabled(config, "advanced_plain_language"):
        if payload["language"] == "de-DE":
            payload["language"] += "-x-simple-language"

        if payload["language"][0:2] == "en":
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

    payload = convert_to_csv(payload, "disabledCategories")
    payload = convert_to_csv(payload, "enabledCategories")
    payload = convert_to_csv(payload, "disabledRules")

    result = await fetch_json_post(
        settings.languagetool_api + "/check",
        payload,
        {},
        "LanguageTool",
        settings.languagetool_verify_ssl,
    )

    return languagetool_matches(
        version, config, client, lang, text, tokens, offsets, result
    )


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
        "utf16_chars": {},
    }

    counter = 0
    for char in [*text]:
        offsets["chars"].append(counter + utf16offset)
        offsets["utf16_chars"][counter + utf16offset] = counter

        counter += 1

        if utf16len(char) > 1 or emoji.is_emoji(char):
            utf16offset += 1

    offsets["chars"].append(counter + utf16offset)
    offsets["utf16_chars"][counter + utf16offset] = counter

    return offsets if utf16offset else False


# matcher to false positives
def is_false_positive_match(false_positive_matcher, i, tokens, lemma):
    if false_positive_matcher is None:
        return False

    index = tokens[i].idx
    for match_id, start, end in false_positive_matcher:
        span_false = tokens[start:end]
        if tokens[start:end].lemma_ != lemma and index in range(
            span_false.start_char, span_false.end_char
        ):
            return True

    return False


# create false positives patterns based on false positives column
def fetch_false_positive_matcher(lang, tokens, false_positives):
    matcher = Matcher(model[lang].vocab)

    for false_positive in false_positives:
        matcher.add("FalsePositivesList", false_positive)

    return matcher(tokens)


def fetch_phrase_matcher(lang, tokens, phrases):
    # Phrase matcher part to handle False positives with two words and special symbols
    matcher = PhraseMatcher(model[lang].vocab, attr="LOWER")

    # Only run model.make_doc to speed things up
    patterns = [model[lang].make_doc(text) for text in phrases]
    matcher.add("TerminologyList", patterns)
    return matcher(tokens)


def fetch_false_positive_matchers(lang, tokens):
    false_positive_matcher = fetch_phrase_matcher(
        lang, tokens, rules[lang]["false_positives_phrases"]
    )

    # create false positives list
    if "pattern_false_positives" not in rules[lang]:
        return false_positive_matcher

    phrase_false_positive_matcher = fetch_false_positive_matcher(
        lang, tokens, rules[lang]["pattern_false_positives"]
    )

    return list(set(phrase_false_positive_matcher + false_positive_matcher))


def parse_client(client: str):
    if client is None:
        client = "0.0.0"

    if ":" in client:
        client = client.split(":")
    else:
        client = ["web-ext", client]

    return Client(name=client[0], version=client[1])


async def apply_language_rules(
    version: float,
    client: Client,
    config: Config,
    configs: dict,
    lang: Language,
    text: str,
):
    tokens = fetch_tokens(lang.lang, text)
    offsets = utf16_offsets(text)

    term_replacements = fetch_term_replacements(configs, tokens, lang.lang)

    match lang.lang:
        case "de":
            list_results = await german_rules(
                version,
                config,
                term_replacements,
                client,
                tokens,
                offsets,
                lang,
                text,
            )
        case "en":
            list_results = await english_rules(
                version,
                config,
                term_replacements,
                client,
                tokens,
                offsets,
                lang,
                text,
            )
        case _:
            list_results = []

    list_results = await apply_languagetool_rules(
        version, config, client, lang, text, tokens, offsets
    ) + await context_false_positives(lang.lang, tokens, list_results)

    return apply_false_positives(list_results, configs)


def fetch_term_replacements(
    configs: dict,
    tokens,
    lang: str,
):
    term_replacements = namedtuple("term_replacements", "rules false_positive_matcher")
    if "term_replacements" not in configs:
        return term_replacements([], None)

    term_replacement_rules = []
    alternatives = []
    for lemma in configs["term_replacements"]:
        term_replacement = configs["term_replacements"][lemma]

        if lemma.endswith("|en") or lemma.endswith("|de"):
            if not lemma.endswith(lang):
                continue

            lemma = lemma[0:-3]

        word_type = (
            term_replacement["word_type"] if "word_type" in term_replacement else "~"
        )

        words = tokenize(lemma, lang)
        word_types = tuple([word_type] * len(words))
        alternatives += term_replacement["alternatives"]

        rule = Rule(
            lemma,
            lang,
            lemma,
            words,
            word_types,
            "corporate_rules",
            term_replacement["alternatives"],
        )

        if term_replacement["explanation"] is not None:
            rule.explanation = term_replacement["explanation"].get("text")
            rule.url = term_replacement["explanation"].get("url")
            rule.icon = term_replacement["explanation"].get("icon")

        term_replacement_rules.append(rule)

    false_positive_matcher = fetch_phrase_matcher(lang, tokens, alternatives)

    return term_replacements(term_replacement_rules, false_positive_matcher)


def apply_false_positives(
    list_results: List,
    configs: dict,
):
    if len(list_results) == 0:
        return list_results

    false_positives = []
    if "false_positives" in configs:
        false_positives = configs["false_positives"]

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
    if lang not in settings.context_checker or len(rules[lang]["context_check"]) == 0:
        return list_results

    sentences = {}
    sentences_to_check = defaultdict(list)
    for i in range(len(list_results)):
        result = list_results[i]
        if result.lemma in rules[lang]["context_check"]:
            if len(sentences) == 0:
                for sentence in tokens.sents:
                    sentences[sentence.end_char] = sentence.text

            sentence = None
            for end_char in sentences:
                if result.end <= end_char:
                    sentence = sentences[end_char]
                    break

            if sentence is None:
                continue

            sentences_to_check[sentence].append(i)

    if sentences_to_check == {}:
        return list_results

    sentences = list(sentences_to_check.keys())

    headers = {
        "Content-Type": "application/json",
        "Authorization": ("Bearer " + settings.context_checker[lang]["api_key"]),
    }

    payload = {
        "data": sentences,
    }

    context_results = await fetch_json_post(
        settings.context_checker[lang]["url"],
        json.dumps(payload),
        headers,
        "context checker",
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


def check_continue(i, new_i, tokens):
    if new_i == i:
        return False

    if new_i < i:
        logging.error("Incorrect new_i: expected %i < %i for %s", i, new_i, tokens[i])

        return False

    return True


def fetch_word_rules(rules, token_lower, lemma_lower, suffix_text=False):
    word_rules = rules[token_lower] if token_lower in rules else []

    if token_lower != lemma_lower and lemma_lower in rules:
        word_rules += rules[lemma_lower]

    # shortest base word, "Arzt"
    if suffix_text is True and lemma_lower[-4:] in rules:
        word_rules += rules[lemma_lower[-4:]]

    return word_rules


async def german_rules(
    version: float,
    config: Config,
    term_replacements: namedtuple,
    client: Client,
    tokens,
    offsets: dict,
    lang: Language,
    text: str,
):
    list_full = []

    i = new_i = 0
    token_count = len(tokens)
    while new_i < token_count:
        i = new_i

        token = tokens[i]
        token_lower = token.text.lower()
        if token.text[0].isupper() and len(token.text) > 3:
            result = german_noun_lookup(token.text, False)
            if (
                result is not None
                and "flexion" in result
                and "nominativ plural" in result["flexion"]
                and "nominativ singular" in result["flexion"]
                and token.lemma_ != result["flexion"]["nominativ singular"]
            ):
                token.lemma_ = token_lower.replace(
                    result["flexion"]["nominativ plural"].lower(),
                    result["flexion"]["nominativ singular"].lower(),
                ).capitalize()

                logging.error(
                    "Missing lemma lookup for '%s' => '%s'", token.text, token.lemma_
                )

        lemma_lower = token.lemma_.lower()

        if len(term_replacements.rules):
            new_i = rule_check(
                version,
                config,
                client,
                lang,
                text,
                i,
                tokens,
                offsets,
                list_full,
                term_replacements.rules,
                term_replacements.false_positive_matcher,
            )

            if check_continue(i, new_i, tokens):
                continue

        if is_sub_category_enabled(config, "gender_specific_abbreviation"):
            new_i = regex_match(
                version,
                config,
                client,
                lang,
                text,
                i,
                tokens,
                offsets,
                list_full,
                rules["m_f_regexes"],
            )

            if check_continue(i, new_i, tokens):
                continue

        subcategory = "d_and_i"
        if is_sub_category_enabled(config, subcategory):
            new_i = regex_match(
                version,
                config,
                client,
                lang,
                text,
                i,
                tokens,
                offsets,
                list_full,
                rules["d_f_m_regexes"],
            )

            if check_continue(i, new_i, tokens):
                continue

            word_types = (
                (-1, 1, config.german_gender_ending[0])
                if config.german_gender_ending[0] == "/"
                else (None, None, config.german_gender_ending[0])
            )

            endings = [
                Rule(
                    config.german_gender_ending + "",
                    "de",
                    config._gendereddenom_ending[config.german_gender_ending],
                    None,
                    config._gendereddenom_ending_word_type[config.german_gender_ending],
                    subcategory,
                ),
            ]

            if config.german_gender_ending in config._gendereddenom_ending_article:
                endings.append(
                    Rule(
                        config.german_gender_ending + " article",
                        "de",
                        config._gendereddenom_ending_article[
                            config.german_gender_ending
                        ],
                        None,
                        word_types,
                        subcategory,
                    )
                )

            new_i = regex_match(
                version,
                config,
                client,
                lang,
                text,
                i,
                tokens,
                offsets,
                list_full,
                endings,
            )

            if check_continue(i, new_i, tokens):
                continue

        subcategory = "advanced_gendered_denominations_ending"
        if is_sub_category_enabled(
            config, subcategory
        ) and ResultOut.genderedRolesFormatInclusive(config.gendered_roles_format):
            endings = []
            for key, regexp in config._gendereddenom_ending.items():
                if config.german_gender_ending == key:
                    continue

                ending = Rule(
                    key + "",
                    "de",
                    regexp,
                    None,
                    config._gendereddenom_ending_word_type[key],
                    subcategory,
                    (config.german_gender_ending,),
                )

                endings.append(ending)

                if (
                    # GermanGenderEndingType.SLASH_DASH is redundant to GermanGenderEndingType.SLASH
                    key != GermanGenderEndingType.SLASH_DASH
                    # only check if relevant regexp is defined
                    and key in config._gendereddenom_ending_article
                ):
                    word_types = (
                        (-1, 2, key[0]) if key[0] == "/" else (None, None, key[0])
                    )

                    ending = Rule(
                        key + "article",
                        "de",
                        config._gendereddenom_ending_article[key],
                        None,
                        word_types,
                        subcategory,
                    )

                    endings.append(ending)

            new_i = regex_match(
                version,
                config,
                client,
                lang,
                text,
                i,
                tokens,
                offsets,
                list_full,
                endings,
            )

            if check_continue(i, new_i, tokens):
                continue

        new_i = detect_non_inclusive_emoji(
            version,
            config,
            client,
            lang,
            text,
            i,
            tokens,
            offsets,
            list_full,
        )

        if check_continue(i, new_i, tokens):
            continue

        new_i = regex_match(
            version,
            config,
            client,
            lang,
            text,
            i,
            tokens,
            offsets,
            list_full,
            rules["de"]["hashtags"],
        )

        if check_continue(i, new_i, tokens):
            continue

        token_text = tokens[i].text
        if len(tokens[i].text) <= 1 or not token_text[0].isalpha():
            new_i += 1
            continue

        new_i = rule_check(
            version,
            config,
            client,
            lang,
            text,
            i,
            tokens,
            offsets,
            list_full,
            fetch_word_rules(
                rules["de"]["open_disc_words_data"],
                token_lower,
                lemma_lower,
            ),
        )

        if check_continue(i, new_i, tokens):
            continue

        new_i = rule_check(
            version,
            config,
            client,
            lang,
            text,
            i,
            tokens,
            offsets,
            list_full,
            rules["de"]["open_disc_words_data_base"],
        )

        if check_continue(i, new_i, tokens):
            continue

        new_i = rule_check(
            version,
            config,
            client,
            lang,
            text,
            i,
            tokens,
            offsets,
            list_full,
            fetch_word_rules(
                rules["de"]["gender_words_data_no_noun"],
                token_lower,
                lemma_lower,
            ),
        )

        if check_continue(i, new_i, tokens):
            continue

        if token.text[0].isupper():
            new_i = rule_check(
                version,
                config,
                client,
                lang,
                text,
                i,
                tokens,
                offsets,
                list_full,
                fetch_word_rules(
                    rules["de"]["gender_words_data"],
                    token_lower,
                    lemma_lower,
                    True,
                ),
            )

        if check_continue(i, new_i, tokens):
            continue

        new_i = rule_check(
            version,
            config,
            client,
            lang,
            text,
            i,
            tokens,
            offsets,
            list_full,
            fetch_word_rules(
                rules["de"]["bias_words_data_no_plur"],
                token_lower,
                lemma_lower,
            ),
        )

        if check_continue(i, new_i, tokens):
            continue

        new_i = rule_check(
            version,
            config,
            client,
            lang,
            text,
            i,
            tokens,
            offsets,
            list_full,
            fetch_word_rules(
                rules["de"]["bias_words_data_noun"],
                token_lower,
                lemma_lower,
            ),
        )

        if check_continue(i, new_i, tokens):
            continue

        new_i = rule_check(
            version,
            config,
            client,
            lang,
            text,
            i,
            tokens,
            offsets,
            list_full,
            fetch_word_rules(
                rules["de"]["style_words_data"],
                token_lower,
                lemma_lower,
            ),
        )

        if check_continue(i, new_i, tokens):
            continue

        if is_sub_category_enabled(config, "abbreviation"):
            new_i = rule_check(
                version,
                config,
                client,
                lang,
                text,
                i,
                tokens,
                offsets,
                list_full,
                fetch_word_rules(
                    rules["de"]["abbreviation"],
                    token_lower,
                    lemma_lower,
                ),
            )

            if check_continue(i, new_i, tokens):
                continue

        if is_sub_category_enabled(config, "communal"):
            new_i = rule_check(
                version,
                config,
                client,
                lang,
                text,
                i,
                tokens,
                offsets,
                list_full,
                fetch_word_rules(
                    rules["de"]["communal_words"],
                    token_lower,
                    lemma_lower,
                ),
            )

            if check_continue(i, new_i, tokens):
                continue

        if is_sub_category_enabled(config, "d_and_i"):
            new_i = rule_check(
                version,
                config,
                client,
                lang,
                text,
                i,
                tokens,
                offsets,
                list_full,
                fetch_word_rules(
                    rules["de"]["d_and_i_words"],
                    token_lower,
                    lemma_lower,
                ),
            )

            if check_continue(i, new_i, tokens):
                continue

        new_i += 1

    return list_full


async def english_rules(
    version: float,
    config: Config,
    term_replacements: namedtuple,
    client: Client,
    tokens,
    offsets: dict,
    lang: Language,
    text: str,
):
    false_positive_matcher = fetch_false_positive_matchers(lang.lang, tokens)

    list_full = []
    i = new_i = 0
    token_count = len(tokens)
    while new_i < token_count:
        i = new_i

        token = tokens[i]
        token_lower = token.text.lower()
        lemma_lower = token.lemma_.lower()

        if len(term_replacements.rules):
            new_i = rule_check(
                version,
                config,
                client,
                lang,
                text,
                i,
                tokens,
                offsets,
                list_full,
                term_replacements.rules,
                term_replacements.false_positive_matcher,
            )

            if check_continue(i, new_i, tokens):
                continue

        if is_sub_category_enabled(config, "gender_specific_abbreviation"):
            new_i = regex_match(
                version,
                config,
                client,
                lang,
                text,
                i,
                tokens,
                offsets,
                list_full,
                rules["m_f_regexes"],
            )

            if check_continue(i, new_i, tokens):
                continue

        if is_sub_category_enabled(config, "d_and_i"):
            new_i = regex_match(
                version,
                config,
                client,
                lang,
                text,
                i,
                tokens,
                offsets,
                list_full,
                rules["d_f_m_regexes"],
            )

            if check_continue(i, new_i, tokens):
                continue

        new_i = detect_non_inclusive_emoji(
            version,
            config,
            client,
            lang,
            text,
            i,
            tokens,
            offsets,
            list_full,
        )

        if check_continue(i, new_i, tokens):
            continue

        new_i = regex_match(
            version,
            config,
            client,
            lang,
            text,
            i,
            tokens,
            offsets,
            list_full,
            rules["en"]["hashtags"],
        )

        if check_continue(i, new_i, tokens):
            continue

        token_text = tokens[i].text
        if len(tokens[i].text) <= 1 or not token_text[0].isalpha():
            new_i += 1
            continue

        new_i = rule_check(
            version,
            config,
            client,
            lang,
            text,
            i,
            tokens,
            offsets,
            list_full,
            fetch_word_rules(
                rules[lang.locale]["open_disc_words_data"],
                token_lower,
                lemma_lower,
            ),
            false_positive_matcher,
        )

        if check_continue(i, new_i, tokens):
            continue

        new_i = rule_check(
            version,
            config,
            client,
            lang,
            text,
            i,
            tokens,
            offsets,
            list_full,
            fetch_word_rules(
                rules[lang.locale]["gender_words_data"],
                token_lower,
                lemma_lower,
            ),
            false_positive_matcher,
        )

        if check_continue(i, new_i, tokens):
            continue

        if is_sub_category_enabled(config, "advanced_binary_pronouns"):
            new_i = rule_check(
                version,
                config,
                client,
                lang,
                text,
                i,
                tokens,
                offsets,
                list_full,
                fetch_word_rules(
                    rules[lang.locale]["bias_singular_they_alternatives"],
                    token_lower,
                    lemma_lower,
                ),
                false_positive_matcher,
            )

            if check_continue(i, new_i, tokens):
                continue

        new_i = rule_check(
            version,
            config,
            client,
            lang,
            text,
            i,
            tokens,
            offsets,
            list_full,
            fetch_word_rules(
                rules[lang.locale]["gender_noun_words_data"],
                token_lower,
                lemma_lower,
            ),
            false_positive_matcher,
        )

        if check_continue(i, new_i, tokens):
            continue

        new_i = rule_check(
            version,
            config,
            client,
            lang,
            text,
            i,
            tokens,
            offsets,
            list_full,
            fetch_word_rules(
                rules[lang.locale]["style_words_data"],
                token_lower,
                lemma_lower,
            ),
            false_positive_matcher,
        )

        if check_continue(i, new_i, tokens):
            continue

        new_i = rule_check(
            version,
            config,
            client,
            lang,
            text,
            i,
            tokens,
            offsets,
            list_full,
            fetch_word_rules(
                rules[lang.locale]["style_noun_words_data"],
                token_lower,
                lemma_lower,
            ),
            false_positive_matcher,
        )

        if check_continue(i, new_i, tokens):
            continue

        new_i = rule_check(
            version,
            config,
            client,
            lang,
            text,
            i,
            tokens,
            offsets,
            list_full,
            fetch_word_rules(
                rules[lang.locale]["bias_words_data"],
                token_lower,
                lemma_lower,
            ),
            false_positive_matcher,
        )

        if check_continue(i, new_i, tokens):
            continue

        new_i = rule_check(
            version,
            config,
            client,
            lang,
            text,
            i,
            tokens,
            offsets,
            list_full,
            fetch_word_rules(
                rules[lang.locale]["gender_bias_words_data"],
                token_lower,
                lemma_lower,
            ),
            false_positive_matcher,
        )

        if check_continue(i, new_i, tokens):
            continue

        new_i = rule_check(
            version,
            config,
            client,
            lang,
            text,
            i,
            tokens,
            offsets,
            list_full,
            fetch_word_rules(
                rules[lang.locale]["homonyms_word"],
                token_lower,
                lemma_lower,
            ),
            false_positive_matcher,
            False,
        )

        if check_continue(i, new_i, tokens):
            continue

        if is_sub_category_enabled(config, "abbreviation"):
            new_i = rule_check(
                version,
                config,
                client,
                lang,
                text,
                i,
                tokens,
                offsets,
                list_full,
                fetch_word_rules(
                    rules[lang.locale]["abbreviation"],
                    token_lower,
                    lemma_lower,
                ),
            )

            if check_continue(i, new_i, tokens):
                continue

        if check_continue(i, new_i, tokens):
            continue

        new_i = rule_check(
            version,
            config,
            client,
            lang,
            text,
            i,
            tokens,
            offsets,
            list_full,
            fetch_word_rules(
                rules[lang.locale]["inclusive_words_data"],
                token_lower,
                lemma_lower,
            ),
            false_positive_matcher,
        )

        if check_continue(i, new_i, tokens):
            continue

        new_i += 1

    return list_full


def parse_word_type(word_type, lower_case=True):
    lemmatize = True

    if word_type is None or word_type == "":
        return "", lower_case, lemmatize

    match word_type[0]:
        case "~":
            # exact match
            lower_case = True
            lemmatize = False
            word_type = word_type[1:]
        case "=":
            # exact match
            lower_case = False
            lemmatize = False
            word_type = word_type[1:]
        case "-":
            # force lower case off
            lower_case = False
            lemmatize = True
            word_type = word_type[1:]

    return word_type, lower_case, lemmatize


def is_word_match(
    lang,
    token,
    word,
    word_type,
    lower_case,
    suffix,
):
    word_type, lower_case, lemmatize = parse_word_type(word_type, lower_case)

    token_word = token.lemma_ if lemmatize else token.text

    if lower_case and (lang == "en" or "s" not in word_type):
        token_word = token_word.lower()
        word = word.lower()

    if token_word != word and (
        not suffix or not token_word.lower().endswith(word.lower())
    ):
        return False

    return check_word_type(lang, token, word_type, True)


def is_phrase_match(
    lang,
    i,
    tokens,
    rule: Rule,
    false_positive_matcher=None,
    lower_case=True,
):
    suffix = rule.type == RuleType.SUFFIX

    word_count = len(rule.words)
    if len(rule.word_types) > 1:
        suffix = False

    text = ""
    for k in range(word_count):
        try:
            if k > 0:
                text += word_token.whitespace_

            word_token = tokens[i + k]
            if not is_word_match(
                lang,
                word_token,
                rule.words[k],
                rule.word_types[k],
                lower_case,
                suffix,
            ):
                return None, False

            text += word_token.text
        except IndexError:
            return None, False

    if is_false_positive_match(false_positive_matcher, i, tokens, rule.lemma):
        return None, False

    return i + k + 1, text


"""Function to change adjectives to -en form in alternatives"""


def fetch_word_type(lang, token, word_type=None, single_word=None):
    # https://machinelearningknowledge.ai/tutorial-on-spacy-part-of-speech-pos-tagging/
    # https://github.com/explosion/spaCy/blob/master/spacy/glossary.py

    if token._.is_emoji:
        return "emoji"

    if word_type is None:
        word_type = ""

    if "adv" in word_type and token.pos_ == "ADV":
        return "adv"

    if (
        lang == "en"
        and "-" in token.text
        and not token.text.startswith("-")
        and not token.text.endswith("-")
    ):
        tokens = fetch_tokens(lang, token.text.replace("-", " "))
        return fetch_word_type(lang, tokens[0], word_type, single_word)

    if token.pos_ == "VERB":
        if lang == "de" and "a" in word_type:
            return "a"

        return "v"

    if token.lemma_ in rules["de"]["verbs"]:
        return "v"

    if token.pos_ == "NOUN" or token.pos_ == "PRON":
        return "n"

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
        return "a"

    if token.tag_ == "NN":
        return "n"

    if token.pos_ == "PROPN" and single_word is not None and len(word_type):
        return word_type[0:1]

    if token.tag_ == "KON" or token.pos_ == "CCONJ":
        return "conj"

    return ""


def check_word_type(lang, token, word_type="", single_word=None):
    if len(word_type) == 0:
        return True

    return word_type == fetch_word_type(lang, token, word_type, single_word)


def find_common_prefix(a_text, a_lemma):
    prefix = a_text.lower()
    while a_lemma[: len(prefix)] != prefix and prefix:
        prefix = prefix[: len(prefix) - 1]
        if not prefix:
            break

    return prefix


def add_declension_german(text, a_text, a_lemma, injected_string=""):
    prefix = find_common_prefix(
        a_text.replace("ä", "a").replace("ö", "o").replace("ü", "u"),
        a_lemma.replace("ä", "a").replace("ö", "o").replace("ü", "u"),
    )
    ending = a_text[len(prefix) :]
    if injected_string and ending[0 : len(injected_string)] == injected_string:
        a_text = prefix + a_text[len(prefix) + len(injected_string) :]
        a_text = a_text.strip()
        prefix = find_common_prefix(a_text, a_lemma)
        ending = a_text[len(prefix) :]

    if (a_lemma[-1] == "t" or a_lemma[-1] == "s") and len(ending) and ending[0] == "e":
        ending = ending[1:]

    if a_lemma == "beste":
        ending = "ste" + ending
        if text[-1] == "t" or text[-1] == "s":
            text += "e"
    else:
        remove = a_lemma[len(prefix) :]
        if remove:
            text = text[0 : -len(remove)]

    if ending != "" and len(text) > 2:
        if text.endswith("em"):
            return text

        if (text[-1] == "t") and (
            ending[0] == "t" or ending[0] == "s" or ending[0] == "n"
        ):
            text += "e"
        elif (text[-1] == "h" or text[-1] == "n") and (
            ending[0] == "t" or ending[0] == "n"
        ):
            text += "e"
        elif text[-1] == "s":
            text += "s"
        elif text[-1] == "e" and ending[0] == "e":
            text = text[0:-1]

    return text + ending


def determine_genus_from_ending(word, german_genus_endings):
    for genus in german_genus_endings:
        for ending in german_genus_endings[genus]:
            if word.endswith(ending):
                return {"genus": genus}

    return None


def german_noun_lookup(word, log=True):
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
    if genus_result is None or "genus" not in genus_result:
        genus_result = determine_genus_from_ending(
            word, rules["de"]["secondary_german_genus_endings"]
        )
        if genus_result is None or "genus" not in genus_result:
            if log:
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
        if result is None:
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
    match token.morph.get("Case"):
        case ["Dat"]:
            flexion = "dativ"
        case ["Gen"]:
            flexion = "genitiv"
        case ["Nom"]:
            flexion = "nominativ"
        case ["Acc"]:
            flexion = "akkusativ"
        case _:
            return None

    flexion += " singular" if token.morph.get("Number") == ["Sing"] else " plural"

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

    if is_singular is True or (is_singular is None and is_token_plural(lang, a_token)):
        return Noun(b_text).plural()

    if is_singular is False:
        return b_text

    return Noun(b_text).singular()


def align_adjective_form_english(a_text, a_token, b_token):
    a_adjective = Adjective(a_text)
    b_adjective = Adjective(b_token.text)

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


def align_adjective_form(lang, a_text, a_token, b_token):
    if lang == "de":
        return add_declension_german(b_token.text, a_text, a_token.lemma_)

    return align_adjective_form_english(a_text, a_token, b_token)


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
            if "a" == fetch_word_type("de", tokens[0]) and "v" == fetch_word_type(
                "de", tokens[1]
            ):
                return prefix

        i += 1

    return False


def align_verb_form_german(a_text, a_token, b_token):
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

    if b_text in rules["de"]["verbs"] and a_token.lemma_ in rules["de"]["verbs"]:
        for form in rules["de"]["verbs"][a_token.lemma_]:
            if rules["de"]["verbs"][a_token.lemma_][form] == a_text:
                return rules["de"]["verbs"][b_token.lemma_][form]

    return add_declension_german(b_text, a_text, a_token.lemma_, injected_string)


def align_verb_form_english(a_text, b_token):
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


def align_verb_form(lang, a_text, a_token, b_token):
    if lang == "de":
        return align_verb_form_german(a_text, a_token, b_token)

    return align_verb_form_english(a_text, b_token)


def tokenize(text, lang):
    return tuple([i.text for i in model[lang].tokenizer(text)])


def alternative_declension(lang, text, token, word_type, prepend_word, alternative):
    (
        parsed_alternative,
        alternative_context,
        remove,
    ) = ResultOut.parse_alternative(alternative)

    alternative_context = (
        "" if alternative_context is None else " ---" + alternative_context
    )

    if (
        not parsed_alternative
        or remove
        or ResultOut.isInspirationAlternative(parsed_alternative)
    ):
        return alternative

    if parsed_alternative.count(" ") > 5:
        return alternative

    word_count = len(tokenize(text, lang))
    if prepend_word:
        word_count -= 1

    alternative_tokens = fetch_tokens(lang, parsed_alternative)
    if word_count > 1:
        # TODO figure out how to modify phrases
        new_alternative = parsed_alternative
        is_plural_alternative = is_token_plural(lang, alternative_tokens[-1])
    else:
        new_alternative = ""
        is_plural_alternative = False

        previous = False
        for i in reversed(range(len(alternative_tokens))):
            alternative_token = alternative_tokens[i]
            alternative_text = alternative_token.text
            if alternative_text != "," and token_is_conjunction(alternative_token):
                previous = False
            else:
                if len(alternative_tokens) == 1:
                    # in this case we just assume it is the same to avoid issues with word type detection
                    alternative_word_type = word_type
                else:
                    alternative_word_type = fetch_word_type(
                        lang, alternative_token, word_type, False
                    )

                if previous is False:
                    if "v" == word_type and (
                        (lang == "en" and i == 0) or "v" in alternative_word_type
                    ):
                        previous = True
                        alternative_text = align_verb_form(
                            lang, text, token, alternative_token
                        )
                    elif "n" == word_type and "n" == alternative_word_type:
                        if is_token_plural(lang, alternative_token):
                            is_plural_alternative = True

                        previous = True
                        alternative_text = align_noun_form(
                            lang, text, token, alternative_token
                        )
                    elif "a" == word_type and "a" == alternative_word_type:
                        previous = True
                        alternative_text = align_adjective_form(
                            lang, text, token, alternative_token
                        )

            new_alternative = (
                alternative_text + alternative_token.whitespace_ + new_alternative
            )

    if (
        lang == "en"
        and prepend_word
        and is_plural_alternative is False
        and not new_alternative.startswith(rules["en"]["a_not_startswith"])
        and not new_alternative.endswith(rules["en"]["uncountables"])
    ):
        new_alternative = (
            "an " + new_alternative
            if new_alternative[0].lower() in ["a", "e", "i", "o", "u"]
            else "a " + new_alternative
        )

    return new_alternative + alternative_context


def alternatives_declension(lang, text, i, tokens, alternatives):
    token = tokens[i]
    start = token.idx

    if alternatives == None or len(alternatives) == 0:
        return text, start, alternatives

    word_type = fetch_word_type(lang, token)
    prepend_word = False
    prev_token = None if i == 0 else tokens[i - 1]

    match lang:
        case "de":
            if "v" == word_type and prev_token and prev_token.text == "zu":
                text = "zu " + text
                start = prev_token.idx
                prepend_word = True
        case "en":
            if prev_token and (
                prev_token.text.lower() == "a" or prev_token.text.lower() == "an"
            ):
                text = prev_token.text + " " + text
                start = prev_token.idx
                prepend_word = True

    if len(word_type) == 0 or (
        text.lower() == token.lemma_.lower() and token.lemma_ != "beste"
    ):
        return text, start, alternatives

    return (
        text,
        start,
        [
            alternative_declension(
                lang, text, token, word_type, prepend_word, alternative
            ).strip()
            for alternative in alternatives
        ],
    )


def match_binary_inclusive_gendered_denom_analysis_de(
    config: Config,
    full_text,
    text,
    tokens,
    i,
    subcategory,
    suffix,
):
    tokens_length = len(tokens)
    token = tokens[i]
    start = token.idx

    if tokens_length <= 2:
        return text, start, subcategory

    for false_positive in rules["de"]["gender_false_positives"]:
        # "foo/bar" case vs. "foo und bar" case
        split_char = "/" if "/" in false_positive else " und "

        false_positive_words = false_positive.lower().split(split_char)

        # [token]/foo - [token] und foo
        check_before = (
            tokens_length > i + 2 and tokens[i + 1].text == split_char.strip()
        )

        # foo/[token] - foo und [token] - foo und [token]n
        check_after = i >= 2 and tokens[i - 1].text == split_char.strip()

        if not check_before and not check_after:
            continue

        if suffix:
            if (
                check_before
                and tokens[i].text.lower().endswith(false_positive_words[0])
                and tokens[i + 2].text.lower().endswith(false_positive_words[1])
            ):
                if "frau" in text.lower():
                    return None, None, None

                new_i = i
                prefix = text[0 : -len(false_positive_words[0])]
            elif (
                check_after
                and tokens[i - 2].text.lower().endswith(false_positive_words[0])
                and (
                    tokens[i].text.lower().endswith(false_positive_words[1])
                    or tokens[i].text.lower().endswith(false_positive_words[1] + "n")
                )
            ):
                new_i = i - 2
                false_positive_length = len(false_positive_words[1])
                if tokens[i].text.lower().endswith(false_positive_words[1] + "n"):
                    false_positive_length += 1

                prefix = text[0:-(false_positive_length)]
            else:
                continue

            if not tokens[new_i].text.startswith(prefix):
                continue
        elif (
            check_before
            and tokens[i].text.lower() == false_positive_words[0]
            and tokens[i + 2].text.lower() == false_positive_words[1]
        ):
            if "frau" in text.lower():
                return None, None, None

            new_i = i
        elif check_after and (
            tokens[i - 2].text.lower() == false_positive_words[0]
            or tokens[i - 2].text.lower() == false_positive_words[0] + "n"
        ):
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

        break

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
        match word["genus"]:
            case "m":
                article_to_check = masculine
            case "f":
                article_to_check = feminine
            case "n":
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
            article_alternative = (
                match_alternative if match_alternative else article_text
            )
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
                else:
                    match alternative_word["genus"]:
                        case "m":
                            article_alternative = match_masculine
                        case "n":
                            article_alternative = match_neuter
                        case "f":
                            article_alternative = match_feminine
                        case _:
                            if alternative.endswith("in"):
                                article_alternative = match_feminine

        if article_alternative != "":
            article_alternative += tokens[i - 1].whitespace_

        alternatives_with_article.append(article_alternative + alternative)

    return alternatives_with_article


def regex_match(
    version: float,
    config: Config,
    client: Client,
    lang,
    full_text,
    i,
    tokens,
    offsets,
    list_full,
    filtered_rules: list[Rule],
    check_case=None,
):
    token = tokens[i]

    for rule in filtered_rules:
        if not is_sub_category_enabled(config, rule.subcategory):
            continue

        connector_string = rule.word_types[-1]
        start = token.idx

        # run regex on exactly the token
        if rule.word_types[0] is None:
            text = check_text = token.text
            if connector_string not in token.text:
                continue

            start_token = i
        else:
            try:
                text = check_text = ""
                start_token = rule.word_types[0] + i
                max_end_token = rule.word_types[1] + i

                if start_token == max_end_token:
                    check_text = token.text
                    connector_string_start = check_text.find(connector_string)
                    if connector_string_start == -1:
                        continue

                    text = check_text[connector_string_start:]
                    start += connector_string_start
                else:
                    multi_part = max_end_token - start_token > 1
                    # "1,2,#" => "#forever"
                    if not multi_part:
                        if token.text != connector_string:
                            continue

                        text = check_text = connector_string
                    elif (
                        start_token + 1 >= len(tokens)
                        or tokens[start_token + 1].text != connector_string
                    ):
                        continue

                while start_token < max_end_token:
                    offset_token = tokens[start_token]

                    check_text += offset_token.text
                    if start_token >= i:
                        text += offset_token.text

                    if offset_token.whitespace_ != "":
                        break

                    start_token += 1
                    if tokens[start_token].text != connector_string:
                        break

                    check_text += connector_string
                    if start_token >= i:
                        text += connector_string

                    if connector_string == "(":
                        connector_string = ")"

                    if (
                        connector_string == ")"
                        and tokens[start_token].text == connector_string
                    ):
                        break

                    start_token += 1
            except IndexError:
                pass

        # handle "Noch besser x/f/m."
        text = text.rstrip(".")
        check_text = check_text.rstrip(".")

        if text == "" or not re.search(rule.lemma, check_text):
            continue

        if connector_string == "I":
            check_text = check_text.lower().capitalize()
            if german_noun_lookup(check_text) is None:
                continue

        # handle "Kund(-innen)"
        if text == ")" and "(" in check_text:
            ending_start = check_text.find("(")
            text = check_text[ending_start:]
            start = tokens[i - 1].idx + ending_start

        subcategory = rule.subcategory
        if rule.is_advanced:
            subcategory = add_advanced(subcategory)

        alternatives = rule.alternatives
        explanation = rule.explanation
        url = rule.url
        icon = rule.icon

        if rule.subcategory == "d_and_i":
            if check_case == "gender_denom" and check_text.islower():
                text_split = text.split(connector_string)
                if (
                    text_split[0] not in rules["de"]["female_articles"]
                    or text_split[1] not in rules["de"]["male_articles"]
                ):
                    continue

        elif rule.subcategory == "gendered_denominations_ending" and rule.is_advanced:
            if check_text.islower():
                if connector_string == "/" and tokens[i - 1].text.islower():
                    text = tokens[i - 1].text + text

                text_split = text.split(connector_string)
                if (
                    text_split[0] not in rules["de"]["female_articles"]
                    or text_split[1] not in rules["de"]["male_articles"]
                ):
                    continue

                alternatives = [
                    text.replace(connector_string, config.german_gender_ending[0])
                ]
            # Kundinnen -> Kund*innen
            elif "innen" in text:
                alternatives = [alternatives[0] + "nen"]
        elif rule.subcategory == "gender_specific_abbreviation":
            parenthesis = (
                i > 0
                and tokens[i - 1].text == "("
                and tokens[i + len(text)].text == ")"
            )

            letters = text
            if parenthesis:
                letters = letters[1:-1]

            letters = text.split("/")

            letters = list(map(lambda x: x.upper(), letters))
            is_lower = text[0].islower()

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

            if parenthesis:
                start -= 1
                text = f"({text})"
                alternative = f"({alternative})"

            context_v = "--- include veterans"
            match lang.lang:
                case "de":
                    context_d = "--- Divers (EU) / m. Behinderung (NA)"
                    context_remove = "--- Nutze geschlechtsneutrale Job-Titel"
                    explanation = "Nenne unterrepräsentierte Gruppen zuerst. Verlinke auf deine Leitlinie zur Gleichstellung."
                case "en":
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

                if without_v is False:
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

        skip_token = start_token + 1

        list_full.append(
            ResultOut.factory(
                version,
                config,
                client,
                lang,
                text,
                token.lemma_,
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

        return skip_token

    return i


def gendered_denom_alternatives(
    tokens, i, config, rule: Rule, text, start, is_singular
):
    token = tokens[i]
    alternatives = rule.alternatives if is_singular else rule.plural_alternatives

    if rule.type == RuleType.SUFFIX:
        alternatives = alternatives.copy()
        prefix = (
            token.lemma_.removesuffix(rule.lemma.lower())
            if len(token.lemma_) != len(rule.lemma)
            else ""
        )

        for k, alternative in enumerate(alternatives):
            alternative = alternative.replace(rule.lemma, token.lemma_)
            if prefix:
                if alternative[0] == "~":
                    alternative = prefix + alternative[1].lower() + alternative[2:]
                if rule.lemma[0] == "A":
                    modified_word = "Ä" + rule.lemma[1:]
                    modified_word_lower = "ä" + rule.lemma[1:]
                    replacement = (
                        token.lemma_[0 : -len(modified_word)] + modified_word_lower
                    )
                    alternative = alternative.replace(
                        modified_word_lower, replacement.lower()
                    )
                    alternative = alternative.replace(modified_word, replacement)
            elif alternative[0] == "~":
                alternative = alternative[1:]

            alternatives[k] = alternative

    if not ResultOut.genderedRolesFormatBinary(config.gendered_roles_format):
        new_alternatives = []
        for alternative in alternatives:
            if "frau" not in alternative.lower() or "mann" not in alternative.lower():
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

    return text, start, alternatives


def is_false_positive(full_text, token, rule):
    if rule.false_positives is None or len(rule.false_positives) == 0:
        return False

    partial_text = full_text[token.idx :]
    for false_positive in rule.false_positives:
        if partial_text.startswith(false_positive):
            return True


def rule_check(
    version: float,
    config: Config,
    client: Client,
    lang,
    full_text,
    i,
    tokens,
    offsets,
    list_full,
    filtered_rules: list[Rule],
    false_positive_matcher=None,
    lower_case=True,
):
    token = tokens[i]

    # check if the user query have false positives
    if token.lemma_ in rules[lang.lang]["false_positives"]:
        # recognise if there is Name of organisation or geographical name in the query
        if len(tokens.ents) > 0:
            return i

    if token.lemma_ == "aber" and lang.lang == "de":
        preceeding_text = full_text[max(0, token.idx - 5) : token.idx]
        if (
            re.search(r"^ *$", preceeding_text) is not None
            or re.search(r"[.!?:,]\s*$", preceeding_text, re.MULTILINE) is not None
        ):
            return i

    for rule in filtered_rules:
        subcategory = rule.subcategory
        if rule.is_advanced:
            subcategory = add_advanced(subcategory)

        if not is_sub_category_enabled(config, subcategory):
            continue

        # Skip case "Juden" if used as a name
        if (
            rule.is_gendered_denom_rule()
            and token.ent_type_ in rules["named_entity_labels"]["names"]
            and token.ent_type_ != "MISC"
            and token.ent_type_ != "ORG"
        ):
            return i

        if rule.type == RuleType.SUBSTRING:
            text = token.text
            token_lower = text.lower()
            count = token_lower.count(rule.lemma.lower())
            if count == 0:
                continue

            if rule.false_positives is not None:
                for false_positive in rule.false_positives:
                    count -= token_lower.count(false_positive.lower())
                    if count <= 0:
                        break

            if count <= 0:
                continue

            skip_token = i + 1
        else:
            skip_token, text = is_phrase_match(
                lang.lang,
                i,
                tokens,
                rule,
                false_positive_matcher,
                lower_case,
            )

            if not text or is_false_positive(full_text, token, rule):
                continue

        if rule.is_gendered_denom_rule():
            is_singular = is_token_singular(lang.lang, token)
            if is_singular is None:
                continue

            (
                text,
                start,
                subcategory,
            ) = match_binary_inclusive_gendered_denom_analysis_de(
                config,
                full_text,
                text,
                tokens,
                i,
                subcategory,
                rule.type == RuleType.SUFFIX,
            )

            if not text:
                continue

            text, start, alternatives = gendered_denom_alternatives(
                tokens, i, config, rule, text, start, is_singular
            )
        else:
            start = token.idx
            alternatives = rule.alternatives
            if alternatives is not None:
                additional_token_count = len(tokenize(rule.lemma, lang.lang)) - 1
                while additional_token_count >= 0:
                    is_plural = is_token_plural(
                        lang.lang, tokens[i + additional_token_count]
                    )
                    if is_plural is None:
                        additional_token_count -= 1
                        continue

                    break

                if is_plural and rule.plural_alternatives is not None:
                    if text in alternatives:
                        continue

                    alternatives = rule.plural_alternatives
                # TODO make it possible to handle cases with multiple alternatives
                elif len(alternatives) == 1 and alternatives[0] == "they":
                    text, alternative = pluralize_they(tokens, i)
                    alternatives = [alternative]
                elif rule.lemma.count(" ") == 0:
                    text, start, alternatives = alternatives_declension(
                        lang.lang, token.text, i, tokens, alternatives
                    )

                    if subcategory == "filler":
                        text, alternatives = detect_filler_words_at_sentence_start(
                            alternatives,
                            text,
                            full_text,
                            start + len(text),
                        )

        list_full.append(
            ResultOut.factory(
                version,
                config,
                client,
                lang,
                text,
                token.lemma_,
                full_text,
                offsets,
                subcategory,
                start,
                None,
                alternatives,
                None,
                rule.explanation,
                rule.url,
                rule.icon,
            )
        )

        return skip_token

    return i


def detect_filler_words_at_sentence_start(alternatives, text, full_text, end):
    if alternatives == ["-"] and text[0].isupper():
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
            and "v" == fetch_word_type("en", tokens[next_i])
        ):
            if token_is_conjunction(tokens[next_i]):
                text += prev_token.whitespace_ + tokens[next_i].text
                alternative += prev_token.whitespace_ + tokens[next_i].text
                prev_token = tokens[next_i]
                next_i += 1
                if len(tokens) <= next_i:
                    break

            text += prev_token.whitespace_ + tokens[next_i].text
            ending_length = -2 if tokens[next_i].text.endswith("hes") else -1
            alternative += prev_token.whitespace_ + tokens[next_i].text[0:ending_length]

            prev_token = tokens[next_i]
            next_i += 1
            if len(tokens) <= next_i:
                break

    return text, alternative


def get_emoji(emoji_text):
    return emoji.emojize(f":{emoji_text}:", language="alias")


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
    config: Config,
    client: Client,
    lang,
    full_text,
    i,
    tokens,
    offsets,
    list_full,
):
    if client.name == "web-ext" and client.version < VersionString("1.28.0.1"):
        return i

    token = tokens[i]
    if not token._.is_emoji:
        return i

    token_count = len(tokens)

    # 👨🏽‍👩🏽‍👧🏽 case https://github.com/carpedm20/emoji/issues/204
    if (i + 1 < token_count and tokens[i + 1].text.endswith("\u200d")) or (
        i > 0 and tokens[i - 1].text.endswith("\u200d")
    ):
        return i

    alternatives = [get_emoji_context(token.text, lang.lang)]

    emoji_description = token._.emoji_desc
    emoji_base = emoji_description.replace(" light skin tone", "")
    emoji_base = emoji_base.replace(" ", "_")

    subcategory = None
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

        if len(emojis) == 0:
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
                        alternative + " " + get_emoji_context(alternative, lang.lang)
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

    if subcategory and len(alternatives) > 1:
        list_full.append(
            ResultOut.factory(
                version,
                config,
                client,
                lang,
                token.text,
                token.lemma_,
                full_text,
                offsets,
                subcategory,
                token.idx,
                None,
                alternatives,
            )
        )

    return i


# want to server to run app.py in the folder app as main app, port=8000 is defaut port for the fast api
# reload=True is debag mode in Flask is on, to set =False, when deploy the app to the production
# might be added host="0.0.0.0"
if __name__ == "__main__":  # pragma: no cover
    # If this is being ran directly as a script, run an internal uvicorn server
    # to service API requests
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level=settings.logging_config_level,
        server_header=False,
    )
