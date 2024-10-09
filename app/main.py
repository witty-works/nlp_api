import os
import uvicorn
import json
import secrets
from typing import Optional, Union
from collections import defaultdict
from inspect import currentframe
import logging
import re

from spacy import displacy
from spacy.tokens import Doc

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

from app.auth_service import get_unverified_token_claims, fetch_user

import secure

from cmp_version import VersionString

from slack_sdk import WebClient
from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
from slack_bolt import Ack, Respond
from app.bolt import get_bolt, process_command_witty
from app.models import (
    Client,
    Config,
    GermanGenderEndingType,
    LangType,
    Language,
    BaseRequestIn,
    RephraseRequestIn,
    CheckRequestIn,
    Result,
    ResultOut,
    ResultsOut,
    RephrasesOut,
    UserConfRequest,
    OrganizationConfRequest,
    ConfResponse,
    UserConfResponse,
    RuleConfig,
    ResultConf,
    ErrorMessage,
    PrettyJSONResponse,
    RuleIn,
    Alternative,
    Rule,
    BasicWordType,
    WordType,
    MetricsType,
)
from app.helper import is_valid_text, remove_gender_ending, utf16_offsets
from app.db import Db
from app.emoji_check import EmojiCheck
from app.rule_check import RuleCheck
from app.regex_check import RegexCheck
from app.nouns import Nouns
from app.verbs import Verbs
from app.adjectives import Adjectives
from app.llm_alternatives import LlmAlternatives
from app.review_prompt import ReviewPrompt
from app.categories import (
    get_category_keys,
    get_parent_category_name,
    is_sub_category_enabled,
)
from app.alternatives import Alternatives
from app.llm_alternatives import LlmAlternatives
from app.languagetool import LanguageTool
from app.db import Db
from app.http import Http
from app.context import AppContext

context = AppContext()


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get("BLACKFIRE_ENABLE_CONTINUOUS_PROFILING"):
        try:
            from blackfire_conprof.profiler import Profiler

            app_name = os.environ.get("PLATFORM_APPLICATION_NAME")
            # app_name += "-worker-%d" % (os.getpid(),)
            profiler = Profiler(application_name=app_name)
            profiler.start()

            print("Profiler started for %s" % app_name)
        except:
            pass

    global context

    context.http = Http(context.settings, context.logger)

    sqlite_logger = logging.getLogger("aiosqlite")
    sqlite_logger.setLevel(logging.ERROR)

    sqlite_logger.setLevel(logging.WARNING)

    context.db = await Db.factory(context.settings, context.languages)
    context.model.db = context.db

    if context.settings.redis_default_rules:
        rules = json.loads(context.settings.redis_default_rules)
        rules["term_replacements"] = parse_term_replacements(rules["term_replacements"])
        email = rules["email"]
        context.redis.db.set(context.redis.get_user_id(email), json.dumps(rules))

    if context.settings.redis_default_organization_rules:
        organization_rules = json.loads(
            context.settings.redis_default_organization_rules
        )
        organization_rules["term_replacements"] = parse_term_replacements(
            organization_rules["term_replacements"]
        )
        key = organization_rules["id"]
        context.redis.db.set(key, json.dumps(organization_rules))

    context.nouns = Nouns(
        context.settings,
        context.logger,
        context.static_rules,
        context.model,
        context.db,
    )
    context.verbs = Verbs(
        context.settings,
        context.logger,
        context.static_rules,
        context.model,
        context.db,
    )
    context.adjectives = Adjectives(context.settings, context.logger, context.db)
    context.alternatives = Alternatives(
        context.settings,
        context.logger,
        context.static_rules,
        context.db,
        context.model,
        context.nouns,
        context.verbs,
        context.adjectives,
    )
    context.languagetool = LanguageTool(
        context.settings,
        context.static_rules,
        context.logger,
        context.categories,
        context.http,
    )
    context.llm_alternatives = LlmAlternatives(context.settings, context.alternatives)
    context.rule_check = RuleCheck(
        context.settings,
        context.logger,
        context.static_rules,
        context.model,
        context.db,
        context.nouns,
        context.verbs,
        context.adjectives,
        context.alternatives,
    )
    context.regex_check = RegexCheck(
        context.settings, context.logger, context.static_rules, context.nouns
    )
    context.emoji_check = EmojiCheck(
        context.settings, context.logger, context.static_rules
    )

    yield

    await context.http.close()
    await context.db.close()


application_name = "Witty NLP API"

app = FastAPI(
    title=application_name,
    version=context.version,
    terms_of_service=context.settings.terms_of_service,
    contact=context.settings.contact,
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

bolt = get_bolt(context.settings)
bolt_handler = AsyncSlackRequestHandler(bolt)


def fetch_current_username(
    credentials: Optional[HTTPBasicCredentials] = Depends(security),
):  # pragma: no cover
    # Credentials are missing
    if credentials is None:
        # Auth is disabled, just proceed
        if not context.settings.api_docs_auth_enabled:
            return "anon"

        # Auth is enabled, raise 401
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Basic"},
        )

    # Verify the credentials as usual
    if not context.settings.api_docs_username or not context.settings.api_docs_password:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Incorrect user configuration",
        )

    correct_username = secrets.compare_digest(
        credentials.username, context.settings.api_docs_username
    )
    correct_password = secrets.compare_digest(
        credentials.password, context.settings.api_docs_password
    )
    if not (correct_username and correct_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Basic"},
        )

    return credentials.username


@app.post(
    "/debug/rephrase",
    response_model=Union[RephrasesOut, Result],
    response_model_exclude_none=True,
    dependencies=[Depends(HTTPBearer(auto_error=False))],
    include_in_schema=not context.settings.is_prod,
)
async def post_debug_rephrase(
    request: Request,
    response: Response,
    rephrase_request_in: RephraseRequestIn,
    username: str = Depends(fetch_current_username),
):
    return await rephrase_sentence(request, response, rephrase_request_in)


@app.post(
    "/v1.0/rephrase",
    response_model=Union[RephrasesOut, Result],
    response_model_exclude_none=True,
    dependencies=[Depends(HTTPBearer(auto_error=False))],
)
async def post_rephrase_v1_0(
    request: Request,
    response: Response,
    rephrase_request_in: RephraseRequestIn,
):
    return await rephrase_sentence(request, response, rephrase_request_in, "1.0")


async def rephrase_sentence(
    request: Request,
    response: Response,
    rephrase_request_in: RephraseRequestIn,
    version: str | None = None,
):
    client = parse_client(rephrase_request_in.client)
    check_client_version(client)

    if version is not None:
        if rephrase_request_in.model is not None:
            return Result.factory("Model can only be set in debug mode")

        rephrase_api_version(version)

        user_email = await fetch_user(
            request, context.settings, context.redis, context.http
        )
        configs = (
            await fetch_configs_for_request(rephrase_request_in, user_email)
            if user_email
            else {}
        )

        if (
            rephrase_request_in.config.plan is None
            or not rephrase_request_in.config.plan.startswith("witty_")
        ):
            response.status_code = status.HTTP_401_UNAUTHORIZED
            return Result.factory("An error occurred: No valid plan on user")

        if not rephrase_request_in.config.llm_alternatives:
            response.status_code = status.HTTP_403_FORBIDDEN
            return Result.factory(
                "An error occurred: Rephrasing via LLM not enabled on user"
            )
    else:
        # debug
        configs = {}

    context.redis.store_metrics(request, configs, version, "rephrase")

    try:
        results = RephrasesOut.factory(
            await context.llm_alternatives.handle(rephrase_request_in)
        )
    except Exception as e:
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        return Result.factory("An error occurred: " + str(e))

    return results


@app.post(
    "/debug/review_prompt",
    response_model=Union[str, Result],
    response_model_exclude_none=True,
    dependencies=[Depends(HTTPBearer(auto_error=False))],
    include_in_schema=not context.settings.is_prod,
)
async def review_prompt(
    request: Request,
    response: Response,
    check_request_in: CheckRequestIn,
) -> Result | str:
    check_request_in.config.disabled_categories.append("communal")
    check_request_in.config.disabled_categories.append("d_and_i")
    check_request_in.config.disabled_categories.append("emotional_security")
    check_request_in.config.disabled_categories.append("orthography")

    check_result = await check(request, response, check_request_in, None)
    if isinstance(check_result, Result):
        return check_result

    if len(check_result.results) == 0:
        return "WITTYNOCHANGES"

    return ReviewPrompt.handle(check_result.results)


@bolt.command("/witty")
async def handle_command_witty(
    body: dict, ack: Ack, respond: Respond, client: WebClient
):  # pragma: no cover
    await ack()

    check_request_in = CheckRequestIn(client="slack:1.0.0", text=body["text"])
    text, language, limit_reached = fetch_text(
        check_request_in, context.model.models.keys()
    )

    if language is None:
        await respond(f"Witty could not determine a language for '{text}'.")
        return

    configs = {}

    try:
        user = await client.users_info(user=body["user_id"])
        configs = await fetch_configs_for_request(
            check_request_in, user.data["user"]["profile"]["email"]
        )
    except KeyError:
        pass

    if configs == {} and context.settings.slack_organization_id:
        configs = await fetch_organization_configs_for_request(
            check_request_in, context.settings.slack_organization_id
        )

    check_request_in.config.__setattr__("alternatives_max_count", None)
    client = parse_client(check_request_in.client)
    results = await apply_language_rules(
        client, check_request_in.config, configs, language, text
    )

    return await process_command_witty(text, language, limit_reached, results, respond)


@app.post("/slack/commands")
async def post_slack_commands(request: Request):  # pragma: no cover
    return await bolt_handler.handle(request)


@app.get("/health")
async def get_health(check_external: bool = False):
    health = {}

    langs = {
        LangType.EN: "Hello guys",
        LangType.DE: "Hallo Kunde",
        LangType.FR: "Je m'appelle Luc",
    }

    for model_name in context.settings.models:
        try:
            lang = model_name[0:2]
            context.model.fetch_tokens(lang, langs[lang])
            health["model_" + lang] = True
        except Exception:
            health["model_" + lang] = False

    if check_external:
        languagetool_health = await context.model.fetch_json_get(
            context.settings.languagetool_api + "/healthcheck",
            {},
            {},
            "LanguageTool",
            context.settings.languagetool_verify_ssl,
            False,
        )

        health["spelling"] = languagetool_health == "OK"
        health["config"] = context.redis.db.ping()

    content = jsonable_encoder(health)

    for key in health:
        if not health[key]:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=content,
            )

    return content


@app.get("/lt", include_in_schema=not context.settings.is_prod)
def get_lt(username: str = Depends(fetch_current_username)):
    return context.settings.languagetool_api


@app.get("/settings", include_in_schema=not context.settings.is_prod)
def get_lt(username: str = Depends(fetch_current_username)):
    return context.settings


@app.get("/docs", include_in_schema=False)
def get_swagger_documentation(
    username: str = Depends(fetch_current_username),
    include_in_schema=not context.settings.is_prod,
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
    if (
        not context.settings.is_prod and context.settings.testing is False
    ):  # pragma: no cover
        return RedirectResponse(url="/docs", status_code=302)

    return application_name + ": https://witty.works"


@app.get(
    "/save_openapi_json",
    include_in_schema=not context.settings.is_prod,
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
    include_in_schema=not context.settings.is_prod,
    response_class=PrettyJSONResponse,
)
async def get_german_gender_ending(
    alternative: str,
    german_gender_ending: GermanGenderEndingType | None = None,
    username: str = Depends(fetch_current_username),
):
    if german_gender_ending is None:
        inclusive = True
        binary = True
    else:
        inclusive = Config.gendered_roles_format_inclusive(german_gender_ending)
        binary = Config.gendered_roles_format_binary(german_gender_ending)

    alternatives, _ = await context.nouns.gendered_alternatives(
        alternative,
        inclusive,
        binary,
        GermanGenderEndingType.STAR[0],
        GermanGenderEndingType.STAR[0],
    )

    return alternatives


@app.get(
    "/debug/declension",
    include_in_schema=not context.settings.is_prod,
    response_class=PrettyJSONResponse,
)
async def get_declension_debug(
    lang: LangType,
    word_type: BasicWordType,
    word: str,
):
    return await context.db.fetch_declensions(lang, word_type, word)


@app.get(
    "/debug/align_form",
    include_in_schema=not context.settings.is_prod,
    response_class=PrettyJSONResponse,
)
async def get_align_form_debug(
    lang: LangType,
    word_type: BasicWordType,
    index: int,
    source_text: str,
    target_text: str,
):
    source_tokens = context.model.fetch_tokens(lang, source_text)
    target_tokens = context.model.fetch_tokens(lang, target_text)

    target_form = await context.rule_check.find_form(
        lang, word_type, index, source_tokens
    )

    if WordType.VERB == word_type:
        return await context.verbs.align_form_verb(
            lang,
            target_form,
            source_tokens[0].text,
            source_tokens[0].lemma_,
            target_tokens[0],
        )

    if WordType.ADJECTIVE == word_type:
        return await context.adjectives.align_form_adjective(
            lang,
            target_form,
            source_tokens[0].text,
            source_tokens[0].lemma_,
            target_tokens[0],
        )

    # if WordType.NOUN == word_type:
    return context.nouns.align_form_noun(
        lang,
        target_form,
        target_tokens[0],
    )


@app.get(
    "/debug/configs",
    include_in_schema=not context.settings.is_prod,
    dependencies=[Depends(HTTPBearer(auto_error=False))],
)
async def get_config_debug(
    user_email: str,
    username: str = Depends(fetch_current_username),
):  # pragma: no cover
    check_request_in = CheckRequestIn(text="")

    try:
        configs = await fetch_user_organization_configs(user_email)
    except HTTPException:
        try:
            configs = await context.redis.fetch_user_configs_from_redis(user_email)
        except HTTPException:
            configs = {}

    result_configs = await fetch_configs_for_request(check_request_in, user_email)
    del result_configs["organization_config"]
    del result_configs["organization_domains"]
    del result_configs["organization_false_positives"]
    del result_configs["organization_term_replacements"]

    return {
        "configs": configs,
        "result_configs": result_configs,
        "check_request_in": check_request_in,
    }


@app.post(
    "/debug/auth",
    include_in_schema=not context.settings.is_prod,
    dependencies=[Depends(HTTPBearer(auto_error=False))],
)
async def post_auth_debug(
    request: Request, check_request_in: CheckRequestIn
):  # pragma: no cover
    user_email = await fetch_user(
        request, context.settings, context.redis, context.http
    )
    if not user_email:
        return user_email

    configs = await fetch_configs_for_request(check_request_in, user_email)

    if "authorization" in request.headers and request.headers[
        "authorization"
    ].lower().startswith("bearer"):
        unverified_claims = get_unverified_token_claims(request)
    else:
        unverified_claims = "using auth token override"

    return {
        "claim": unverified_claims,
        "configs": configs,
        "check_request_in": check_request_in,
    }


@app.get(
    "/debug/metrics",
    dependencies=[Depends(HTTPBearer(auto_error=False))],
)
async def get_user_configs(
    key: MetricsType,
    top_x: int | None,
    username: str = Depends(fetch_current_username),
):
    result = {}
    keys = MetricsType if key == MetricsType.ALL else [key]
    for _key in keys:
        if _key == MetricsType.ALL:
            continue

        metrics = context.redis.db.hgetall(_key)

        for a in metrics:
            metrics[a] = int(metrics[a])

        result[_key] = {
            k: metrics[k] for k in sorted(metrics, key=metrics.get, reverse=True)
        }
        if top_x is not None:
            result[_key] = {
                dkey: value for dkey, value in list(result[_key].items())[0:top_x]
            }

    if key != MetricsType.ALL:
        return result[key]

    return result


@app.post(
    "/v2.0/auth",
    response_model=Union[ResultConf, dict, None],
    response_model_exclude_none=True,
    dependencies=[Depends(HTTPBearer(auto_error=False))],
)
async def post_auth_2_0(
    request: Request, check_request_in: BaseRequestIn | None = None
):
    client = parse_client(
        check_request_in.client if check_request_in is not None else None
    )
    check_client_version(client)

    user_email = await fetch_user(
        request, context.settings, context.redis, context.http
    )
    configs = (
        await fetch_configs_for_request(CheckRequestIn(text=""), user_email)
        if user_email
        else {}
    )

    context.redis.store_metrics(request, configs, "2.0", "auth")

    if configs == {}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
        )

    config = fetch_result_conf(configs)

    if "team_analytics" in configs and not configs["team_analytics"]:
        config.organization_id = None

    return config


@app.post(
    "/debug/rule",
    include_in_schema=not context.settings.is_prod,
    response_model=list[ResultOut],
    response_model_exclude_none=True,
)
async def post_debug_rule(
    rule_data: RuleIn,
    username: str = Depends(fetch_current_username),
):
    language = context.languages[rule_data.lang]
    config = Config(plan="witty_teams")

    tokens = context.model.fetch_tokens(language.lang, rule_data.text)
    for token in tokens:
        if token.text in rule_data.lemmatizations:
            token.lemma_ = rule_data.lemmatizations[token.text]

    offsets = utf16_offsets(rule_data.text)
    false_positive_matcher = context.model.fetch_false_positive_matchers(
        language.lang, tokens
    )

    if rule_data.alternatives is not None:
        alternative_list = []
        for alternative_in in rule_data.alternatives:
            alternative = Alternative(
                alternative_in.lemma,
                context.model.tokenize(alternative_in.lemma, rule_data.lang),
                alternative_in.word_types,
                alternative_in.is_remove,
                alternative_in.is_inspiration,
                alternative_in.is_placeholder,
                alternative_in.is_advanced,
                alternative_in.is_collective_noun,
                alternative_in.is_gendered_noun,
                alternative_in.label,
            )

            alternative_list.append(alternative)
    else:
        alternative_list = None

    rule = Rule(
        "test",
        rule_data.lang,
        rule_data.lemma,
        context.model.tokenize(rule_data.lemma, rule_data.lang),
        rule_data.word_types,
        rule_data.subcategories,
        alternative_list,
        rule_data.actual_word_types,
    )

    rule.pattern = rule_data.pattern
    rule.is_pattern_match = rule_data.is_pattern_match
    rule.false_positives = rule_data.false_positives
    rule.label = rule_data.label
    rule.type = rule_data.type
    rule.entity_type = rule_data.entity_type
    rule.pluralization = rule_data.pluralization

    rules = [rule]

    list_full = []
    client = parse_client("debug:" + context.version)

    token_index = 0
    token_count = len(tokens)
    while token_index < token_count:
        if rule_data.lang == LangType.DE:
            tokens[token_index].lemma_ = await german_lemmatization(tokens, token_index)

        for rule in rules:
            await context.rule_check.handle(
                config,
                client,
                language,
                rule_data.text,
                token_index,
                tokens,
                offsets,
                list_full,
                [rule],
                false_positive_matcher,
            )

        token_index += 1

    return list_full


@app.get(
    "/debug/spacy",
    include_in_schema=not context.settings.is_prod,
    response_class=PrettyJSONResponse,
)
async def get_debug_spacy(
    text: str,
    lang: LangType,
    detailed: bool = False,
    username: str = Depends(fetch_current_username),
):
    results = []
    tokens = context.model.fetch_tokens(lang, text)

    word_type_rule = None
    for token_index in range(len(tokens)):
        token = tokens[token_index]
        if word_type_rule is None:
            word_type_rule = ""
        else:
            word_type_rule += "|"

        if lang == LangType.DE:
            token.lemma_ = await german_lemmatization(tokens, token_index)
        word_type = await context.model.fetch_word_type(lang, token)
        if token.text != token.lemma_:
            word_type_rule += "~"
        word_type_rule += word_type

        token_info = {
            "text": token.text,
            "lemma": token.lemma_,
            "word_type": word_type,
            "is_singular": context.model.is_token_singular(lang, token),
            "ner": token.ent_type_,
        }

        if detailed:
            token_info["start"] = token.idx
            token_info["whitespace"] = token.whitespace_
            token_info["emoji_desc"] = token._.emoji_desc
            token_info["is_emoji"] = token._.is_emoji
            token_info["morph"] = token.morph.to_dict()
            token_info["tag"] = token.tag_
            token_info["pos"] = token.pos_
            token_info["dep"] = token.dep_
            token_info["head"] = token.head.text

            dependent = None
            children = []
            for a in token.ancestors:
                for atok in a.children:
                    children.append(
                        {"dep": atok.dep_, "token": atok.text, "ner": atok.ent_type_}
                    )
                    if dependent is None and atok.dep_ in ["pobj", "dobj"]:
                        dependent = atok.text

            token_info["dependent"] = dependent
            token_info["children"] = children

        results.append(token_info)

    if detailed:
        noun_chunks = []
        for chunk in tokens.noun_chunks:
            noun_chunks.append(
                {
                    "text": chunk.text,
                    "start": chunk.start,
                    "end": chunk.end,
                }
            )

        results = [{"noun chunks": noun_chunks}] + results

    return [{"auto-detected word type": word_type_rule}] + results


@app.get(
    "/debug/displacy",
    include_in_schema=not context.settings.is_prod,
)
async def get_debug_spacy(
    text: str,
    lang: LangType,
    username: str = Depends(fetch_current_username),
):
    tokens = context.model.fetch_tokens(lang, text)

    sentence_spans = list(tokens.sents)
    data = displacy.render(sentence_spans, style="dep")
    return Response(content=data, media_type="image/svg+xml")


@app.get(
    "/debug/german_noun",
    include_in_schema=not context.settings.is_prod,
    response_class=PrettyJSONResponse,
)
async def get_debug_german_noun(
    word: str,
    username: str = Depends(fetch_current_username),
):
    return await context.nouns.german_noun_lookup(word)


@app.post(
    "/debug/check",
    response_model=Union[ResultsOut, Result],
    response_model_exclude_none=True,
    dependencies=[Depends(HTTPBearer(auto_error=False))],
    include_in_schema=not context.settings.is_prod,
)
async def post_debug_check(
    request: Request,
    response: Response,
    check_request_in: CheckRequestIn,
    username: str = Depends(fetch_current_username),
):
    return await check(request, response, check_request_in)


@app.post(
    "/v2.4/check",
    response_model=Union[ResultsOut, Result],
    response_model_exclude_none=True,
    dependencies=[Depends(HTTPBearer(auto_error=False))],
)
async def post_check_v2_3(
    request: Request,
    response: Response,
    check_request_in: CheckRequestIn,
):
    return await check(request, response, check_request_in, "2.4")


@app.get("/lemmatize")
async def get_lemmatize(
    text: str,
    lang: LangType,
    all: bool = False,
    username: str = Depends(fetch_current_username),
):
    tokens = context.model.fetch_tokens(lang, text)
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
    return context.model.tokenize(text, lang)


@app.get("/parse-word-types")
async def get_tokenize(
    text: str,
    word_types: str,
    lang: LangType,
    username: str = Depends(fetch_current_username),
):
    tokens = context.model.fetch_tokens(lang, text)
    word_type_list = word_types.split("|")

    if len(tokens) != len(word_type_list):
        raise RequestValidationError(
            f"Word type '{word_types}' count does not match text token count '{len(tokens)}' for text '{text}'."
        )

    parsed_word_types = []
    for word_type in word_type_list:
        parsed_word_type, lower_case, lemmatize = parse_word_type(word_type)

        if (
            parsed_word_type != ""
            and parsed_word_type not in context.supported_word_types
        ):
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
    status_code=status.HTTP_204_NO_CONTENT,
)
async def post_organization_configs(
    organization_configs: OrganizationConfRequest,
    username: str = Depends(fetch_current_username),
):
    organization_configs.term_replacements = parse_term_replacements(
        organization_configs.term_replacements
    )

    context.redis.db.set(
        organization_configs.id, organization_configs.model_dump_json()
    )


@app.delete(
    "/organization/configs",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_organiztion_configs(
    organization_id: str,
    username: str = Depends(fetch_current_username),
):
    context.redis.db.delete(organization_id)


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
    return await context.redis.fetch_organization_configs_from_redis(organization_id)


@app.post(
    "/user/configs",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def post_user_configs(
    user_configs: UserConfRequest, username: str = Depends(fetch_current_username)
):
    user_configs.term_replacements = parse_term_replacements(
        user_configs.term_replacements
    )

    context.redis.db.set(
        context.redis.get_user_id(user_configs.email), user_configs.model_dump_json()
    )


@app.delete(
    "/user/configs",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_user_configs(
    email: str,
    username: str = Depends(fetch_current_username),
):
    context.redis.db.delete(context.redis.get_user_id(email))


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
    return await fetch_user_organization_configs(email)


def fetch_text(
    check_request_in: CheckRequestIn, supported_langs: list
) -> tuple[str, Language | None, bool]:
    text = check_request_in.text
    limit_reached = len(text) > context.settings.text_max_length
    if limit_reached:
        text = text[0 : context.settings.text_max_length]
        text = text.rsplit(" ", 1)[0]

    locale = context.lang_detection.get_locale(
        supported_langs,
        text,
        check_request_in.lang,
        check_request_in.config.preferred_languages,
        check_request_in.config.preferred_variants,
    )

    language = None if locale is None else context.languages[locale]

    return text, language, limit_reached


def parse_term_replacement(lemma, term_replacement: dict):
    word_type = (
        term_replacement["word_type"] if "word_type" in term_replacement else "~"
    )

    word_type, lower_case, lemmatize = parse_word_type(word_type)

    word_type = tuple(
        [
            {
                "word_type": word_type,
                "lower_case": lower_case,
                "lemmatize": lemmatize,
            }
        ]
    )

    if lower_case and not lemmatize:
        lemma = lemma.lower()

    if list(filter(lemma.endswith, context.term_replacement_langs)) != []:
        term_replacement["lang"] = lemma[-2:]
        term_replacement["lemma"] = lemma[0:-3]
    else:
        term_replacement["lang"] = None
        term_replacement["lemma"] = lemma

    lang = LangType.EN if term_replacement["lang"] is None else term_replacement["lang"]
    term_replacement["words"] = context.model.tokenize(term_replacement["lemma"], lang)
    term_replacement["word_types"] = word_type * len(term_replacement["words"])

    term_replacement["false_positives"] = []
    term_replacement["parsed_alternatives"] = []
    for alternative in term_replacement["alternatives"]:
        term_replacement["false_positives"].append(alternative)

        alternative = {"lemma": alternative}
        alternative["words"] = context.model.tokenize(alternative["lemma"], lang)
        alternative["word_types"] = word_type * len(alternative["words"])
        term_replacement["parsed_alternatives"].append(alternative)

    return term_replacement


def parse_term_replacements(term_replacements_source: dict | None = None):
    term_replacements = {}
    if term_replacements_source is not None:
        for lemma in term_replacements_source:
            term_replacement = dict(term_replacements_source[lemma])
            term_replacement = parse_term_replacement(lemma, term_replacement)

            term_replacements[lemma] = term_replacement

    return term_replacements


async def fetch_user_organization_configs(email: str) -> dict | None:
    configs = await context.redis.fetch_user_configs_from_redis(email)

    configs["organization_name"] = None
    configs["organization_config_hash"] = None
    configs["organization_domains"] = None
    configs["organization_trial_ends_at"] = None

    if "organization_id" in configs and configs["organization_id"] is not None:
        organization_configs = (
            await context.redis.fetch_organization_configs_from_redis(
                configs["organization_id"]
            )
        )

        if "plan" not in configs or configs["plan"] is None:
            configs["plan"] = organization_configs["plan"]

        if "trial_ends_at" in organization_configs:
            configs["organization_trial_ends_at"] = organization_configs[
                "trial_ends_at"
            ]

        configs["organization_name"] = organization_configs["name"]

        configs["organization_config_hash"] = (
            organization_configs["config_hash"]
            if "config_hash" in organization_configs
            else None
        )

        configs["organization_domains"] = (
            organization_configs["domains"] if "domains" in organization_configs else {}
        )

        configs["organization_config"] = organization_configs["config"]

        configs["organization_term_replacements"] = organization_configs[
            "term_replacements"
        ]

        configs["organization_false_positives"] = organization_configs[
            "false_positives"
        ]
    else:
        configs["organization_id"] = None

    return configs


def apply_configs(
    check_request_in: CheckRequestIn,
    configs: dict,
    plan: str,
    force_disables: bool = True,
):
    disabled_categories = check_request_in.config.disabled_categories
    if "force_categories" not in configs or configs["force_categories"] is None:
        configs["force_categories"] = []

    for config in configs:
        if config == "force_categories":
            continue

        data = configs[config]
        if data is None:
            continue

        if config == "categories":
            for category in data:
                category_data = data[category]
                if category_data["status"] != "force":
                    continue

                # BC handling for old category names -> needs to be fixed in the dashboard
                if category.startswith("advanced_"):
                    category = category.removeprefix("advanced_") + "_advanced"

                if category_data["value"]:
                    if category in disabled_categories:
                        disabled_categories.remove(category)
                else:
                    force_disables_category = force_disables
                    if not force_disables_category and len(configs["force_categories"]):
                        parent_category = get_parent_category_name(category)
                        force_disables_category = (
                            parent_category in configs["force_categories"]
                        )

                    if force_disables_category and category not in disabled_categories:
                        disabled_categories.append(category)
        elif config == "store_context":
            if (
                plan is not None
                and plan != "witty_free"
                and data["status"] == "force"
                and not data["value"]
            ):
                check_request_in.config.__setattr__("store_context", False)
        elif config == "llm_alternatives":
            if (
                plan is not None
                and plan != "witty_free"
                and data["status"] == "force"
                and data["value"]
            ):
                check_request_in.config.__setattr__("llm_alternatives", True)
        elif data["status"] == "force":
            check_request_in.config.__setattr__(config, data["value"])

    check_request_in.config.__setattr__("disabled_categories", disabled_categories)
    check_request_in.config.__setattr__("plan", plan)


async def fetch_configs_for_request(
    request_in: BaseRequestIn, user_email=Optional[str]
) -> dict:
    request_in.config.__setattr__("store_context", True)
    request_in.config.__setattr__("llm_alternatives", False)
    request_in.config.__setattr__("plan", None)
    request_in.config.__setattr__(
        "alternatives_max_count", context.settings.alternatives_max_count
    )

    if not user_email:
        request_in.config.__setattr__("disabled_categories", get_category_keys(True))
        request_in.config.__setattr__("plan", None)

        return {}

    try:
        configs = await fetch_user_organization_configs(user_email)
    except HTTPException:
        return {}

    apply_configs(request_in, configs["config"], configs["plan"])

    if "organization_config" in configs:
        apply_configs(
            request_in,
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
    request_in: BaseRequestIn, organization_id=Optional[str]
) -> dict:
    request_in.config.__setattr__("store_context", True)
    request_in.config.__setattr__("llm_alternatives", False)

    if not organization_id:
        return {}

    try:
        configs = await context.redis.fetch_organization_configs_from_redis(
            organization_id
        )
    except HTTPException:
        return {}

    for config in configs["configs"]:
        if configs["configs"][config]["status"] == "suggestion":
            configs["configs"][config]["status"] = "force"

    apply_configs(request_in, configs["config"], configs["plan"])

    return configs


def rephrase_api_version(version: str):
    if version != "1.0":  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"API version '{version}' not supported, please use version '1.0'.",
        )


def check_api_version(version: str):
    if version != "2.4":  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"API version '{version}' not supported, please use version '2.4'.",
        )


def check_client_version(client: Client):
    if (
        client.name in context.settings.minimum_versions
        and client.version
        < VersionString(context.settings.minimum_versions[client.name])
    ):  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Client version '{client.version}' not supported, please use at least '{context.settings.minimum_versions[client.name]}'.",
        )


async def check(
    request: Request,
    response: Response,
    check_request_in: CheckRequestIn,
    version: str | None = None,
) -> Result | ResultsOut:
    client = parse_client(check_request_in.client)
    check_client_version(client)

    if version is not None:
        check_api_version(version)

        user_email = await fetch_user(
            request, context.settings, context.redis, context.http
        )
        configs = await fetch_configs_for_request(check_request_in, user_email)
    else:
        # debug
        user_email = None

        if "none" in check_request_in.config.disabled_categories:
            check_request_in.config.__setattr__("disabled_categories", [])
        elif check_request_in.config.disabled_categories == []:
            check_request_in.config.__setattr__(
                "disabled_categories", ["plain_language_advanced"]
            )

        configs = {"categories": {}}
        apply_configs(check_request_in, configs, "witty_teams")

    context.redis.store_metrics(request, configs, version, "check")

    if (
        check_request_in.config.plan is not None
        and check_request_in.config.plan.startswith("witty_")
    ):
        text, language, limit_reached = fetch_text(
            check_request_in, context.model.models.keys()
        )

        if language is None:
            response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
            return Result.factory("Language could not be determined")

        results = await apply_language_rules(
            client, check_request_in.config, configs, language, text
        )

        lang = language.lang

        if isinstance(results, Result):
            return results
    else:
        results = []
        lang = LangType.EN
        limit_reached = False

    notifications = None
    if "notifications" in configs and configs["notifications"] > 0:
        notifications = configs["notifications"]

    has_consented_to_mailing = None
    if "has_consented_to_mailing" in configs:
        has_consented_to_mailing = configs["has_consented_to_mailing"]

    return ResultsOut(
        results=results,
        language=lang,
        limit_reached=limit_reached,
        config_changed=fetch_config_change(configs, check_request_in),
        notifications=notifications,
        has_consented_to_mailing=has_consented_to_mailing,
    )


def fetch_config_change(
    configs: dict,
    check_request_in: Optional[BaseRequestIn] = None,
) -> bool | None:
    if not check_request_in:
        return True

    if (
        "config_hash" in configs
        and check_request_in.config_hash != configs["config_hash"]
    ):
        return True

    if (
        "organization_config_hash" in configs
        and check_request_in.organization_config_hash
        != configs["organization_config_hash"]
    ):
        return True

    return None


def fetch_result_conf(configs: dict) -> ResultConf | None:
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
        organization_trial_ends_at=configs["organization_trial_ends_at"],
    )


def parse_client(client: str) -> Client:
    if client is None:
        client = "0.0.0"

    if ":" in client:
        client = client.split(":")
    else:
        client = ["web-ext", client]

    return Client(name=client[0], version=client[1])


async def apply_language_rules(
    client: Client,
    config: Config,
    configs: dict,
    language: Language,
    text: str,
) -> list:
    tokens = context.model.fetch_tokens(language.lang, text)
    offsets = utf16_offsets(text)

    term_replacements = fetch_term_replacements(configs, language.lang)

    list_results = await witty_rules(
        config,
        term_replacements,
        client,
        tokens,
        offsets,
        language,
        text,
    )

    list_results = await context.languagetool.apply_languagetool_rules(
        config, client, language, text, tokens, offsets
    ) + await context_false_positives(language.lang, tokens, list_results)

    return apply_false_positives(list_results, configs)


def fetch_term_replacements(
    configs: dict,
    lang: LangType,
) -> list[Rule]:
    if "term_replacements" not in configs:
        return []

    term_replacement_rules = []
    for lemma in configs["term_replacements"]:
        if lemma.endswith("|en") or lemma.endswith("|de"):
            if not lemma.endswith(lang):
                continue

        term_replacement = configs["term_replacements"][lemma]

        alternatives = []
        for alternative in term_replacement["parsed_alternatives"]:
            alternatives.append(
                Alternative(
                    alternative["lemma"],
                    alternative["words"],
                    alternative["word_types"],
                )
            )

        rule = Rule(
            term_replacement["lemma"],
            lang,
            term_replacement["lemma"],
            term_replacement["words"],
            term_replacement["word_types"],
            "corporate_rules",
            alternatives,
        )

        if term_replacement["explanation"] is not None:
            rule.explanation = term_replacement["explanation"].get("text")
            rule.url = term_replacement["explanation"].get("url")
            rule.icon = term_replacement["explanation"].get("icon")

        if term_replacement["word_types"][0]["lower_case"]:
            rule.false_positives = term_replacement["false_positives"]
        else:
            rule.case_sensitive_false_positives = term_replacement["false_positives"]

        term_replacement_rules.append(rule)

    return term_replacement_rules


def apply_false_positives(
    list_results: list,
    configs: dict,
) -> list:
    if len(list_results) == 0:
        return list_results

    false_positives = []
    if "false_positives" in configs:
        false_positives = configs["false_positives"]

    if len(false_positives):
        for result in list_results.copy():
            if result.text in false_positives:
                list_results.remove(result)

    return list_results


async def context_false_positives(
    lang: LangType, tokens: Doc, list_results: list[ResultOut]
):
    if (
        lang not in context.settings.context_checker
        or len(context.static_rules[lang]["context_check"]) == 0
    ):
        return list_results

    sentences = {}
    sentences_to_check = defaultdict(list)
    for result_index in range(len(list_results)):
        result = list_results[result_index]
        if result.text_id in context.static_rules[lang]["context_check"]:
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

            sentences_to_check[sentence].append(result_index)

    if sentences_to_check == {}:
        return list_results

    sentences = list(sentences_to_check.keys())

    headers = {
        "Content-Type": "application/json",
        "Authorization": (
            "Bearer " + context.settings.context_checker[lang]["api_key"]
        ),
    }

    payload = {
        "data": sentences,
    }

    context_results = await context.http.fetch_json_post(
        context.settings.context_checker[lang]["url"],
        json.dumps(payload),
        headers,
        "context checker",
    )

    keys_to_remove = []
    for sentence_index in range(len(sentences)):
        sentence = sentences[sentence_index]
        if context_results[sentence_index] == "1":
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


def check_continue(
    list_full: list, token_index: int, new_token_index: int, tokens: Doc, func_name: str
):
    if new_token_index == token_index:
        return False

    if new_token_index < token_index:
        cf = currentframe()

        text_id = list_full[-1].text_id if len(list_full) else ""

        context.logger.error(
            "Incorrect new_token_index on line %i using '%s': expected %i < %i for '%s' versus '%s' for text_id '%s'",
            cf.f_back.f_lineno,
            func_name,
            token_index,
            new_token_index,
            tokens[token_index].text,
            tokens[new_token_index].text,
            text_id,
        )

        return False

    return True


async def german_lemmatization(tokens: Doc, token_index: int):
    token = tokens[token_index]
    word_type = await context.model.fetch_word_type(LangType.DE, token)

    match word_type:
        case WordType.NOUN:
            if (
                token.text != token.lemma_
                or not token.text[0].isupper()
                or len(token.text) <= 3
            ):
                return token.lemma_

            word = remove_gender_ending(token.text)

            result = await context.nouns.german_noun_lookup(word, token)
            if result is not None:
                target = "male_form" if result["male_form"] else "base_form"
                return result[target]
        case WordType.VERB:
            verb_form = token.morph.get("VerbForm")
            verb_form = verb_form[0] if len(verb_form) else ""

            if verb_form not in context.verb_form_map:
                return token.lemma_

            column_name = False
            if isinstance(context.verb_form_map[verb_form], dict):
                tense = token.morph.get("Tense")
                tense = tense[0] if len(tense) else ""
                person = token.morph.get("Person")
                person = person[0] if len(person) else ""

                if (
                    tense in context.verb_form_map[verb_form]
                    and person in context.verb_form_map[verb_form][tense]
                ):
                    parameters = [token.text + "%"]
                    operator = "LIKE"
                    column_name = context.verb_form_map[verb_form][tense][person]
            else:
                if token_index > 0 and tokens[token_index - 1].text == "zu":
                    parameters = ["zu " + token.text]
                    prev = True
                else:
                    parameters = [token.text]
                    prev = False
                operator = "="
                column_name = context.verb_form_map[verb_form]

            if column_name:
                table_name = context.declensions_config[LangType.DE][WordType.VERB][
                    "name"
                ]
                query = f"SELECT base_form, {column_name} FROM {table_name} WHERE {column_name} {operator} ? LIMIT 1"

                rows = await context.db.fetch_rows(query, parameters)
                if len(rows):
                    if operator == "LIKE":
                        token_index_offset = 1
                        for sentence_token in token.sent:
                            if sentence_token.i > token.i:
                                token_index_offset += 1
                                if (
                                    tokens[token_index].text
                                    + " "
                                    + sentence_token.text.lower()
                                    == rows[0][1]
                                ):
                                    if (
                                        sentence_token.text.lower() == "schwarz"
                                        and token_index_offset > 2
                                    ):
                                        sentence_token._.connected_token = token
                                        token._.child_token = sentence_token
                                        token._.label = sentence_token._.label = (
                                            tokens[token_index].text
                                            + " .. "
                                            + sentence_token.text.lower()
                                        )
                                    else:
                                        token._.token_index_offset = token_index_offset

                                    await context.db.fetch_declensions(
                                        LangType.DE, WordType.VERB, rows[0][0], token
                                    )

                                    token._.form = column_name
                                    if token_index_offset == 2:
                                        token._.text = (
                                            tokens[token_index].text
                                            + tokens[token_index].whitespace_
                                            + sentence_token.text
                                        )
                                    return rows[0][0]
                        return token.lemma_

                    if prev:
                        token._.start = tokens[token_index - 1].idx
                        token._.text = (
                            tokens[token_index - 1].text
                            + tokens[token_index - 1].whitespace_
                            + tokens[token_index].text
                        )
                        token._.form = column_name

                    await context.db.fetch_declensions(
                        LangType.DE, WordType.VERB, rows[0][0]
                    )
                    return rows[0][0]

    return token.lemma_


async def german_gender_endings(
    config: Config,
    client: Client,
    tokens: Doc,
    offsets: dict,
    language: Language,
    text: str,
    token_index: int,
    list_full: list,
) -> int:
    # shallow check to see if any of the delimeters is even contained
    if not re.search("[/):_*I]", text):
        return token_index

    subcategory = "d_and_i"
    if is_sub_category_enabled(config.disabled_categories, subcategory):
        word_types = (
            (-1, 1, config.german_gender_ending[0])
            if config.german_gender_ending[0] == "/"
            else (None, None, config.german_gender_ending[0])
        )

        endings = [
            Rule(
                config.german_gender_ending + "",
                LangType.DE,
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
                    LangType.DE,
                    config._gendereddenom_ending_article[config.german_gender_ending],
                    None,
                    word_types,
                    subcategory,
                )
            )

        new_token_index = await context.regex_check.handle(
            config,
            client,
            language,
            text,
            token_index,
            tokens,
            offsets,
            list_full,
            endings,
        )

        if check_continue(
            list_full, token_index, new_token_index, tokens, "regex_match"
        ):
            return new_token_index

    subcategory = "gendered_denominations_ending_advanced"
    if is_sub_category_enabled(
        config.disabled_categories, subcategory
    ) and Config.gendered_roles_format_inclusive(config.gendered_roles_format):
        endings = []
        for key, regexp in config._gendereddenom_ending.items():
            if config.german_gender_ending == key:
                continue

            ending = Rule(
                key + "",
                LangType.DE,
                regexp,
                None,
                config._gendereddenom_ending_word_type[key],
                subcategory,
                [Alternative(config.german_gender_ending)],
            )

            endings.append(ending)

            if (
                # GermanGenderEndingType.SLASH_DASH is redundant to GermanGenderEndingType.SLASH
                key != GermanGenderEndingType.SLASH_DASH
                # only check if relevant regexp is defined
                and key in config._gendereddenom_ending_article
            ):
                word_types = (-1, 2, key[0]) if key[0] == "/" else (None, None, key[0])

                ending = Rule(
                    key + "article",
                    LangType.DE,
                    config._gendereddenom_ending_article[key],
                    None,
                    word_types,
                    subcategory,
                )

                endings.append(ending)

        new_token_index = await context.regex_check.handle(
            config,
            client,
            language,
            text,
            token_index,
            tokens,
            offsets,
            list_full,
            endings,
        )

        if check_continue(
            list_full, token_index, new_token_index, tokens, "regex_match"
        ):
            return new_token_index

    return token_index


async def witty_rules(
    config: Config,
    term_replacements: list[Rule],
    client: Client,
    tokens: Doc,
    offsets: dict,
    language: Language,
    text: str,
) -> list:
    false_positive_matcher = (
        None
        if language.lang == LangType.DE
        else context.model.fetch_false_positive_matchers(language.lang, tokens)
    )

    list_full = []

    token_index = new_token_index = 0
    token_count = len(tokens)
    while new_token_index < token_count:
        token_index = new_token_index

        token = tokens[token_index]
        if token._.connected_token is not None:
            new_token_index += 1
            continue

        if language.lang == LangType.DE:
            token.lemma_ = await german_lemmatization(tokens, token_index)

        if len(term_replacements):
            new_token_index = await context.rule_check.handle(
                config,
                client,
                language,
                text,
                token_index,
                tokens,
                offsets,
                list_full,
                term_replacements,
            )

            if check_continue(
                list_full, token_index, new_token_index, tokens, "rule_check"
            ):
                continue

        if is_sub_category_enabled(
            config.disabled_categories, "gender_specific_abbreviation"
        ):
            new_token_index = await context.regex_check.handle(
                config,
                client,
                language,
                text,
                token_index,
                tokens,
                offsets,
                list_full,
                context.static_rules["m_f_regexes"],
            )

            if check_continue(
                list_full, token_index, new_token_index, tokens, "regex_match"
            ):
                continue

        new_token_index = context.emoji_check.handle(
            config,
            client,
            language,
            text,
            token_index,
            tokens,
            offsets,
            list_full,
        )

        if check_continue(
            list_full,
            token_index,
            new_token_index,
            tokens,
            "detect_non_inclusive_emoji",
        ):
            continue

        token_text = tokens[token_index].text

        if token_text[0] == "#":
            new_token_index = await context.regex_check.handle(
                config,
                client,
                language,
                text,
                token_index,
                tokens,
                offsets,
                list_full,
                context.static_rules[language.lang]["hashtags"],
            )

            if check_continue(
                list_full, token_index, new_token_index, tokens, "regex_match"
            ):
                continue

        valid_text = is_valid_text(language.lang, token_text)
        if valid_text:
            new_token_index = await context.rule_check.handle(
                config,
                client,
                language,
                text,
                token_index,
                tokens,
                offsets,
                list_full,
                None,
                false_positive_matcher,
            )

            if check_continue(
                list_full, token_index, new_token_index, tokens, "rule_check"
            ):
                continue

            new_token_index = await context.rule_check.handle(
                config,
                client,
                language,
                text,
                token_index,
                tokens,
                offsets,
                list_full,
                None,
                false_positive_matcher,
                True,
            )

            if check_continue(
                list_full, token_index, new_token_index, tokens, "rule_check"
            ):
                continue

        if language.lang == LangType.DE:
            new_token_index = await german_gender_endings(
                config,
                client,
                tokens,
                offsets,
                language,
                text,
                token_index,
                list_full,
            )

            if check_continue(
                list_full, token_index, new_token_index, tokens, "german_rule"
            ):
                continue

        new_token_index += 1

    return list_full


def parse_word_type(word_type: str, lower_case: bool = True) -> tuple[str, bool, bool]:
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
        log_level=context.settings.logger_config_level,
        server_header=False,
    )
