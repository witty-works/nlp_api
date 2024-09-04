import os
import re
import uvicorn
import json
import secrets
import aiohttp
from typing import Optional, Union, List
from collections import defaultdict
import fasttext
import aiosqlite
from copy import deepcopy
from inspect import currentframe
import json_repair

from spacy.matcher import PhraseMatcher, Matcher
from spacy import displacy
from spacy.tokens import Token, Doc
from spacy.tokens.span import Span

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
    get_unverified_token_claims,
    decode_b2c_jwt,
    decode_jwt,
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
    LangVariantType,
    Language,
    BaseRequestIn,
    RephraseRequestIn,
    CheckRequestIn,
    Result,
    ResultOut,
    ResultsOut,
    RephraseOut,
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
    RuleLabelEnum,
    EntityType,
    PluralizationType,
    BasicWordType,
    WordType,
    AlternativeType,
    MetricsType,
)
from app.lang_detection import get_lang_detection
from app.categories import (
    get_category_keys,
    get_categories,
    get_category,
    get_parent_category_name,
    get_category_name,
)
from app.settings import get_settings
from app.logger import LoggerSetup
from app.redis import get_user_id, RedisSetup
from app.model import fetch_nlp_model
from app.rules import fetch_static_rules
from app.sentry import set_up_sentry_sdk
from app.query_definitions import (
    rule_columns,
    rule_column_list,
    alternative_columns,
    alternative_column_list,
    declensions_config,
    verb_form_map,
    noun_form_map,
)
import boto3

version = "2.3.0"

categories = get_categories()
settings = get_settings()
logger = LoggerSetup(settings).get_logger()
logger.debug("app started with settings: %s", settings)

sentry_sdk = set_up_sentry_sdk(version, settings)
redis = RedisSetup(settings).get_redis()


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

    check_request_in = CheckRequestIn(client="slack:1.0.0", text=body["text"])
    text, lang, limit_reached = fetch_text(check_request_in, model.keys())

    if lang is None:
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

    if configs == {} and settings.slack_organization_id:
        configs = await fetch_organization_configs_for_request(
            check_request_in, settings.slack_organization_id
        )

    check_request_in.config.__setattr__("alternatives_max_count", None)
    client = parse_client(check_request_in.client)
    results = await apply_language_rules(
        client, check_request_in.config, configs, lang, text
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
        for result_index, result in enumerate(results):
            issue_text = f"#{result_index+1} Matched Text: {result.text} (category {result.category}, proficiency_level {result.proficiency_level})\n"

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
                    block_id=f"match{result_index}",
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
                        block_id=f"alternatives{result_index}",
                        text=MarkdownTextObject(text=alternatives),
                    )
                )

    await respond(blocks=blocks)


async def get_rules_db(import_from_dump: bool = True):
    global rules_db

    in_memory_url = "file:rules_db?mode=memory&cache=shared&uri=true"
    rules_db = await aiosqlite.connect(in_memory_url, check_same_thread=False)

    tables_exist = await fetch_rows(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='rules_rule'"
    )
    if len(tables_exist) == 0:
        if import_from_dump:
            await rules_db.executescript(open("./database/dump.sql", "r").read())
        else:
            source = await aiosqlite.connect("./database/db.sqlite3")
            await source.backup(rules_db)
            await source.close()

    return rules_db


async def fetch_rows(query, parameters=None) -> list:
    cursor = await rules_db.execute(query, parameters)
    rows = await cursor.fetchall()
    await cursor.close()

    return rows


def create_rule(lang, row, rewrite_to: str|None = None) -> Rule:
    rule = Rule(
        row[rule_columns["id"]],
        row[rule_columns["language"]],
        row[rule_columns["lemma"]],
        json.loads(row[rule_columns["lemma_json"]]),
        json.loads(row[rule_columns["word_types_json"]]),
        json.loads(row[rule_columns["diversity_dimension_json"]]),
        None,
        row[rule_columns["actual_word_types"]],
    )

    if rewrite_to:
        rule.lemma = Language.convert_to(rule.lemma, LangVariantType.enGB)
        rule.words = Language.convert_to(rule.words, LangVariantType.enGB)

    rule.text_id = row[rule_columns["text_id"]]
    rule.parent_id = row[rule_columns["parent_id"]]
    rule.pattern = row[rule_columns["pattern"]]
    rule.is_pattern_match = row[rule_columns["is_pattern_match"]]
    rule.label = (
        row[rule_columns["label"]]
        if row[rule_columns["label"]]
        else map_rule_label_type(lang, row[rule_columns["label_type"]])
    )
    rule.label_type = row[rule_columns["label_type"]]
    rule.type = row[rule_columns["type"]]
    rule.pluralization = row[rule_columns["pluralization"]]
    rule.entity_type = row[rule_columns["entity_type"]]

    return rule


async def fetch_false_positives(rule: Rule, rewrite_to: str|None = None) -> list[str]:
    if rule.false_positives is not None:
        return rule.false_positives

    query = "SELECT false_positive FROM rules_falsepositive WHERE rule_id = ?"
    parameters = [rule.id]

    false_positives = []
    rows = await fetch_rows(query, parameters)
    for row in rows:
        false_positives.append(row[0])
        if rewrite_to:
            false_positive = Language.convert_to(row[0], rewrite_to)
            if row[0] != false_positive:
                false_positives.append(false_positive)

    return false_positives


static_rules = fetch_static_rules()

supported_word_types = list(WordType._member_map_.values())

with open("./training_data/lookup.json", "r") as fp:
    lookup = json.load(fp)

with open("./training_data/lemma_plural_lookup.json", "r") as fp:
    lemma_plural_lookup = json.load(fp)

model = {}
Token.set_extension("word_type", default=None)
Token.set_extension("text", default=None)
Token.set_extension("start", default=None)
Token.set_extension("label", default=None)
Token.set_extension("form", default=None)
Token.set_extension("forms", default=None)
Token.set_extension("token_index_offset", default=1)
Token.set_extension("child_token", default=None)
Token.set_extension("connected_token", default=None)
for spacy_model in settings.models:
    lang = spacy_model[0:2]

    lookup[lang] = lookup[lang] if lang in lookup else []
    lemma_plural_lookup[lang] = (
        lemma_plural_lookup[lang] if lang in lemma_plural_lookup else []
    )
    model[lang] = fetch_nlp_model(lang, spacy_model, lookup[lang])

lookup = None

if settings.fasttext:
    pretrained_lang_model = os.getcwd() + "/training_data/lid.176.bin"
    fasttext_model = fasttext.load_model(pretrained_lang_model)

session = None
ssl_session = None
rules_db = None
substring_rules = {}
male_to_female_normativ = {}
person_words = {
    LangType.EN: [],
    LangType.DE: [],
}
misc_words = {
    LangType.EN: [],
    LangType.DE: [],
}
label_types = {
    LangType.DE: {
        RuleLabelEnum.BE_SPECIFIC: "Sei spezifisch",
        RuleLabelEnum.NOT_FOR_PEOPLE: "Nicht auf Menschen beziehen",
        RuleLabelEnum.NAME_DISABILITY: "Nenne die Behinderung oder Zustand",
        RuleLabelEnum.ONLY_IF_GENDER_IDENTITY_RELEVANT: "Nur erwähnen, wenn relevant",
        RuleLabelEnum.NOT_FOR_NON_COMBAT: "Nur in einen Kampf-Kontext verwenden",
        RuleLabelEnum.ASK_FOR_PREFERENCE: "Nur wenn die Person sich so bezeichnet",
        RuleLabelEnum.ONLY_WHEN_REFERENCING_RELIGIOUS_PRACTICE: "Nur in Bezug auf die religiöse Praxis verwenden",
        RuleLabelEnum.USE_IN_TECH_ONLY: "Nur im Programmier-Kontext verwenden",
        RuleLabelEnum.DONT_USE_TO_DESCRIBE_QUALITY: "Nicht zur Beschreibung von Wert oder Qualität verwenden",
        RuleLabelEnum.DONT_USE_FOR_SUBSTANCE_USE: "Nicht im Zusammenhang mit Drogenkonsum verwenden",
        RuleLabelEnum.ASK_ABOUT_TRADITIONS: "Frage nach ihren Traditionen",
    },
    LangType.EN: {
        RuleLabelEnum.BE_SPECIFIC: "Be specific",
        RuleLabelEnum.NOT_FOR_PEOPLE: "Don't use this phrase for people",
        RuleLabelEnum.NAME_DISABILITY: "Name the disability or condition",
        RuleLabelEnum.ONLY_IF_GENDER_IDENTITY_RELEVANT: "Only if gender identity is relevant",
        RuleLabelEnum.NOT_FOR_NON_COMBAT: "Only use in a combat context",
        RuleLabelEnum.ASK_FOR_PREFERENCE: "Only if preference explicitly stated",
        RuleLabelEnum.ONLY_WHEN_REFERENCING_RELIGIOUS_PRACTICE: "Only use in reference to religious practice",
        RuleLabelEnum.USE_IN_TECH_ONLY: "Use in programming only",
        RuleLabelEnum.DONT_USE_TO_DESCRIBE_QUALITY: "Don't use to describe value or quality",
        RuleLabelEnum.DONT_USE_FOR_SUBSTANCE_USE: "Don't use in the context of substance use",
        RuleLabelEnum.ASK_ABOUT_TRADITIONS: "Ask about their traditions",
    },
}


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

    global session
    global ssl_session
    global rules_db
    global substring_rules
    global person_words
    global misc_words

    global settings
    global model
    global redis

    import logging

    logger = logging.getLogger("aiosqlite")
    logger.setLevel(logging.ERROR)

    session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False))
    ssl_session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=True))

    rules_db = await get_rules_db(settings.import_from_dump)

    for lang in model:
        query = f"SELECT {rule_column_list} FROM rules_rule WHERE language = ? and type = ? ORDER BY lemma_length DESC, first_is_word_type_lemmatize ASC"
        parameters = [lang, RuleType.SUBSTRING]
        rows = await fetch_rows(query, parameters)

        substring_rules[lang] = {}
        for row in rows:
            rule = create_rule(lang, row)
            rule.false_positives = await fetch_false_positives(rule)
            substring_rules[lang][rule.lemma.lower()] = rule

            rewrite_to = (
                LangVariantType.enGB if lang == LangType.EN else LangVariantType.deCH
            )
            rewritten_lemma = Language.convert_to(rule.lemma, rewrite_to)
            if rule.lemma != rewritten_lemma:
                rule = create_rule(lang, row, rewrite_to)
                rule.false_positives = await fetch_false_positives(rule, rewrite_to)
                substring_rules[lang][rule.lemma.lower()] = rule

        if lang in declensions_config:
            query = f"SELECT base_form FROM {declensions_config[lang][BasicWordType.NOUN]["name"]} WHERE ner IN (?, ?)"
            parameters = ["person", "group"]
            rows = await fetch_rows(query, parameters)

            for row in rows:
                person_words[lang].append(row[0].lower())

            query = f"SELECT base_form FROM {declensions_config[lang][BasicWordType.NOUN]["name"]} WHERE ner = ?"
            parameters = ["misc"]
            rows = await fetch_rows(query, parameters)

            for row in rows:
                misc_words[lang].append(row[0].lower())

            if lang == "de":
                query = f"SELECT base_form, female_form FROM {declensions_config[lang][BasicWordType.NOUN]["name"]} WHERE female_form IS NOT NULL"
                parameters = [lang, RuleType.SUBSTRING]
                rows = await fetch_rows(query)

                for row in rows:
                    male_to_female_normativ[row[0]] = row[1]

    logger.setLevel(logging.WARNING)

    if settings.redis_default_rules:
        rules = json.loads(settings.redis_default_rules)
        rules["term_replacements"] = parse_term_replacements(rules["term_replacements"])
        email = rules["email"]
        redis.set(get_user_id(email), json.dumps(rules))

    if settings.redis_default_organization_rules:
        organization_rules = json.loads(settings.redis_default_organization_rules)
        organization_rules["term_replacements"] = parse_term_replacements(
            organization_rules["term_replacements"]
        )
        key = organization_rules["id"]
        redis.set(key, json.dumps(organization_rules))

    yield

    await session.close()
    await ssl_session.close()
    await rules_db.close()


application_name = "Witty NLP API"

app = FastAPI(
    title=application_name,
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
lt_style_categories_plain_language = [
    "FALSE_FRIENDS",  # rubber vs. eraser
    "REGIONALISMS",  # use of regional terms
    "COLLOQUIALISMS",  # use of slang
    "CONFUSED_WORDS",  # proscribed vs prescribed
    "REDUNDANCY",  # f.e. "tuna fish" https://community.languagetool.org/rule/list?offset=0&max=10&lang=en&filter=&categoryFilter=Redundant+Phrases&_action_list=Filter
    "STYLE",  # https://community.languagetool.org/rule/list?offset=0&max=10&lang=en&filter=&categoryFilter=Style&_action_list=Filter
]


lt_style = [
    "REPETITIONS",  #
    "REPETITIONS_STYLE",  # Start sentences with same word multiple times https://community.languagetool.org/rule/list?offset=0&max=10&lang=en&filter=&categoryFilter=Repetitions+%28Style%29&_action_list=Filter
    "SEMANTICS",  # She will join us on the 34th of Nov. https://community.languagetool.org/rule/list?offset=0&max=10&lang=en&filter=&categoryFilter=Semantics&_action_list=Filter
]

adj_tags = {
    "AFX",
    "ADJA",
    "ADJD",
    "ADV",
    "ADJ",
    "JJ",
    "JJR",
    "JJS",
    "VVPP",
    "VAPP",
    "VMPP",
}

pronoun_tags = [
    "PDAT",
    "PDS",
    "PIAT",
    "PIDAT",
    "PIS",
    "PPER",
    "PPOSAT",
    "PPOSS",
    "PRELAT",
    "PRELS",
    "PRF",
    "PRP$",
    "PRON",
    "PDT",
    "WP$",
    "WDT",
]

lang_map = {
    "en": "English",
    "de": "German",
    "fr": "French",
}

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

@app.post(
    "/debug/rephrase",
    response_model=Union[RephrasesOut, Result],
    response_model_exclude_none=True,
    dependencies=[Depends(HTTPBearer(auto_error=False))],
    include_in_schema=not settings.is_prod,
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

        user_email = await fetch_user(request)
        configs = await fetch_configs_for_request(rephrase_request_in, user_email) if user_email else {}

        if (
            rephrase_request_in.config.plan is None
            or not rephrase_request_in.config.plan.startswith("witty_")
        ):
            response.status_code = status.HTTP_401_UNAUTHORIZED
            return Result.factory("An error occurred: No valid plan on user")
    else:
        # debug
        configs = {}

    aws_model_id = settings.aws_model_id if rephrase_request_in.model is None else rephrase_request_in.model

    store_metrics(request, configs, version, "rephrase")

    # Initialize the Bedrock runtime client
    aws_client = boto3.client(
        service_name="bedrock-runtime",
        region_name=settings.aws_region_name,
        aws_access_key_id=settings.aws_key,
        aws_secret_access_key=settings.aws_secret_key,
    )

    placeholder = "|---|"
    sentence = rephrase_request_in.sentence
    alternatives = []
    genderstar = {}
    for alternative_index in range(len(rephrase_request_in.alternatives)):
        alternative = rephrase_request_in.alternatives[alternative_index]
        if alternative.types is None:
            alternatives.append(alternative.lemma)
        else:
            genderstar[alternative_index] = alternative.types
            alternatives.append(alternative.male_form)
            alternatives.append(alternative.female_form)

    alternatives = list(set(alternatives))

    text = rephrase_request_in.text
    start = rephrase_request_in.start
    lang = lang_map[rephrase_request_in.lang]

    end = start + len(text)

    # The updated prompt specifies that the assistant should only replace the word at the specified position
    system_prompt = f"""
    You are an expert in {lang} grammatical correctness.
    Make sure that all grammatical and spelling mistakes present in 'sentence' are still present in each of the 'rephrasing' in the output.
    Replace '{placeholder}' in 'sentence_with_placeholder' with each of the supplied items in 'alternatives'.
    Before making the replacement ensure that the alternative matches the {lang} grammatical case (tense, pluralization etc.) of the supplied 'text' (ie. if 'text' is past tense the 'alternatives' should all also be made past tense).
    Do not make stylistic or other unnecessary changes in the output.
    Change as little as necessary to make the output grammatically correct in {lang} like correcting the gender of the article to match the 'alternative' preceeding '{placeholder}' it.
    For each item in 'alternatives' provide exactly one item ('alternative' + 'rephrasing') in the response with key in the dictionary matching exactly each of the 'alternative' provided.
    Leave double parenthesis unchanged.
    """

    match rephrase_request_in.lang:
        case LangType.DE:
            system_prompt+= f"""
                Make sure to not remove any useage of the Genderstar.

                For the following example:  
                {{
                    "sentence": "Einhaltung von ethischen Prinzipien.",
                    "sentence_with_placeholder": "Einhaltung von ethischen {placeholder}.",
                    "text": "Prinzipien",
                    "alternatives": [
                        "Ethik",
                        "Methode",
                        "Wert",
                        "Richtlinie",
                        "Regel"
                    ]
                }}

                Format the output as follows making sure it is valid JSON:
                {{
                    "Ethik": "Einhaltung von ethischen Ethiken.",
                    "Methode": "Einhaltung von ethischen Methoden.",
                    "Wert": "Einhaltung von ethischen Werte.",
                    "Richtlinie": "Einhaltung von ethischen Richtlinien.",
                    "Regel": "Einhaltung von ethischen Regeln."
                }}

                For the following example:
                {{
                    "sentence": "Wir arbeiten für unsere Kund*innen, für uns ist der Kunde im Zentrum",
                    "sentence_with_placeholder": "Wir arbeiten für unsere Kund*innen, für uns ist der {placeholder} im Zentrum",
                    "text": "Kunden",
                    "alternatives": [
                        "Kunde",
                        "Kundin",
                        "Kundschaft"
                    ]
                }}

                Format the output as follows making sure it is valid JSON:
                {{
                    "Kunde": "Wir arbeiten für unsere Kund*innen, für uns ist der Kunde im Zentrum",
                    "Kundin": "Wir arbeiten für unsere Kund*innen, für uns ist die Kundin im Zentrum",
                    "Kundschaft": "Wir arbeiten für unsere Kund*innen, für uns ist die Kundschaft im Zentrum"
                }}
                """
        case LangType.FR:
            system_prompt+= f"""
                Make sure to not remove any useage of the point médian.

                For the following example:  
                {{
                    "sentence": "Face à la concurrence, il était handicapé par son jeune âge.",
                    "sentence_with_placeholder": "Face à la concurrence, il {placeholder} par son jeune âge.",
                    "text": "était handicapé",
                    "alternatives": [
                        "être désavantagée",
                        "être désavantagé"
                        "être pénalisée",
                        "être pénalisé"
                    ]
                }}

                Format the output as follows making sure it is valid JSON:
                {{
                    "être désavantagée": "Face à la concurrence, elle était désavantagée par son jeune âge.",
                    "être désavantagé": "Face à la concurrence, il était désavantagé par son jeune âge.",
                    "être pénalisée": "Face à la concurrence, elle était pénalisée par son jeune âge.",
                    "être pénalisé": "Face à la concurrence, il était pénalisé par son jeune âge."
                }}

                For the following example:
                {{
                    "sentence": "Les beaux traducteurs sont compétent.",
                    "sentence_with_placeholder": "Les {placeholder} sont compétent.",
                    "text": "traducteurs",
                    "alternatives": [
                        "traducteur,
                        "traductrice",
                        "traduction"
                    ]
                }}

                Format the output as follows making sure it is valid JSON:
                {{
                    "traducteur": "Les beaux traducteurs sont compétent.",
                    "traductrice": "Les belles traductrices sont compétentes.",
                    "traduction": "La beau traduction est compétente"
                }}
                """
        #case LangType.EN:
        case _:
            system_prompt+= f"""
                For the following example:  
                {{
                    "sentence": "Wat he had done is amazing as he is the best.",
                    "sentence_with_placeholder": "Wat {placeholder} has done is amazing as he is the best.",
                    "text": "he",
                    "alternatives": [
                        "they",
                        "he or she",
                        "((given name))"
                    ]
                }}

                Format the output as follows making sure it is valid JSON:
                {{
                    "they": "Wat they have done is amazing as he is the best.",
                    "he or she": "Wat he or she have done is amazing as he is the best.",
                    "((given name))": "Wat ((given name)) have done is amazing as he is the best."
                }}

                For the following example:
                {{
                    "sentence": "We analyzed if this works",
                    "sentence_with_placeholder": "We {placeholder} if this works",
                    "text": "analyzed",
                    "alternatives": [
                        "closely examine"
                    ]
                }}

                Format the output as follows making sure it is valid JSON:
                {{
                    "closely examine": "We closely examined if this works"
                }}
                """
    new_sentence_start = "" if start == 0 else sentence[0:start]
    new_sentence_end = "" if end >= len(sentence) else sentence[end:]
    sentence_with_placeholder = new_sentence_start + placeholder + new_sentence_end

    input_data = {
        "sentence": sentence,
        "sentence_with_placeholder": sentence_with_placeholder,
        "text": text,
        "alternatives": alternatives
    }

    user_prompt = "Please process the following input into a valid JSON response:\n" + json.dumps(input_data)

    conversation = []

    if "mistral" in aws_model_id:
        user_prompt = f"{system_prompt}\n{user_prompt}"
        system_prompt = []
    else:
        system_prompt = [
            {
                "text": system_prompt
            }
        ]

    user_prompt = {
        "role": "user",
        "content": [
            {
                "text": user_prompt
            }
        ],
    }

    conversation.append(user_prompt)

    result = ""

    try:
        streaming_response = aws_client.converse_stream(
            system=system_prompt,
            modelId=aws_model_id,
            messages=conversation,
            inferenceConfig={
                # This is the maximum number of tokens that the LLM generates.
                "maxTokens": 300,
                # Temperature is a hyperparameter that controls the randomness of language model output. (lower is more predictable)
                "temperature": 0.1,
                # Top p, also known as nucleus sampling, is another hyperparameter that controls the randomness of language model output.
                "topP": 1
            },
        )

        for chunk in streaming_response["stream"]:
            if "contentBlockDelta" in chunk:
                text = chunk["contentBlockDelta"]["delta"]["text"]
                result += text

        result = result[result.find("{") : result.rfind("}") + 1]
        result = json_repair.loads(result)

        if rephrase_request_in.gender_separator is None:
            separator = noun_separator = "∙"
        else:
            separator, noun_separator = get_german_noun_separator(rephrase_request_in.gender_separator)

        results = []
        for alternative_index in range(len(rephrase_request_in.alternatives)):
            alternative = rephrase_request_in.alternatives[alternative_index]
            if alternative_index in genderstar:
                if (alternative.male_form in result
                    and placeholder not in result[alternative.male_form]
                    and alternative.female_form in result
                    and placeholder not in result[alternative.female_form]
                ):
                    rephrasings = await noun_alternatives(
                        rephrase_request_in.lang,
                        separator,
                        noun_separator,
                        result[alternative.male_form],
                        result[alternative.female_form],
                    )

                    result_label = alternative.male_form + "/" + alternative.female_form
                    for gendered_role_format in genderstar[alternative_index]:
                        if gendered_role_format in rephrasings:
                            results.append(
                                RephraseOut(
                                    alternative=gendered_role_format + ":" + result_label,
                                    rephrasing=rephrasings[gendered_role_format],
                                )
                            )
            elif alternative.lemma in result and placeholder not in result[alternative.lemma]:
                results.append(
                    RephraseOut(alternative=alternative.lemma, rephrasing=result[alternative.lemma])
                )

        return RephrasesOut.factory(results)
    except Exception as e:
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        return Result.factory("An error occurred: " + str(e))


@app.post(
    "/debug/review_prompt",
    response_model=Union[str, Result],
    response_model_exclude_none=True,
    dependencies=[Depends(HTTPBearer(auto_error=False))],
    include_in_schema=not settings.is_prod,
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

    prompt = f"""You are an expert in inclusive language.
You are tasked with editing the text that you just generated.
Show the before and after and explain the changes using the explanation hints given below.

For each item in the below "JSON issues list", replace the content provided in "issue" within the "text" using any of the provided alternatives.
Pick which ever alternatives fits best in the given context either using the "alternative" or if "remove" is set to True, try to remove the given "issue" from the text entirely.
If no "alternatives" are provided, try to rephrase the given text portion.
Use content in "explanation" to explain your changes.
"""

    changes = []
    for result in check_result.results:
        change = {
            "text": result.text,
            "explanation": result.explanation.text,
        }
        
        if len(result.alternatives):
            alternatives = []
            for alternative in result.alternatives:
                if alternative.remove:
                    alternatives.append({"remove": True})
                else:
                    alternatives.append({"alternative": alternative.text})

        changes.append(change)

    return prompt + "\nJSON issues list:\n" + json.dumps(changes)


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

    return application_name + ": https://witty.works"


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
async def get_german_gender_ending(
    alternative: str,
    german_gender_ending: GermanGenderEndingType | None = None,
    username: str = Depends(fetch_current_username),
):
    if german_gender_ending is None:
        inclusive = True
        binary = True
    else:
        inclusive = gendered_roles_format_inclusive(german_gender_ending)
        binary = gendered_roles_format_binary(german_gender_ending)

    alternatives, _ = await gendered_alternatives(
        alternative,
        inclusive,
        binary,
        GermanGenderEndingType.STAR[0],
        GermanGenderEndingType.STAR[0],
    )

    return alternatives


@app.get(
    "/debug/declension",
    include_in_schema=not settings.is_prod,
    response_class=PrettyJSONResponse,
)
async def get_declension_debug(
    lang: LangType,
    word_type: BasicWordType,
    word: str,
):
    return await fetch_declensions(lang, word_type, word)


@app.get(
    "/debug/align_form",
    include_in_schema=not settings.is_prod,
    response_class=PrettyJSONResponse,
)
async def get_align_form_debug(
    lang: LangType,
    word_type: BasicWordType,
    index: int,
    source_text: str,
    target_text: str,
):
    source_tokens = fetch_tokens(lang, source_text)
    target_tokens = fetch_tokens(lang, target_text)

    target_form = await find_form(lang, word_type, index, source_tokens)

    if WordType.VERB == word_type:
        return await align_form_verb(
            lang,
            target_form,
            source_tokens[0].text,
            source_tokens[0].lemma_,
            target_tokens[0],
        )

    if WordType.ADJECTIVE == word_type:
        return await align_form_adjective(
            lang,
            target_form,
            source_tokens[0].text,
            source_tokens[0].lemma_,
            target_tokens[0],
        )

    # if WordType.NOUN == word_type:
    return align_form_noun(
        lang,
        target_form,
        target_tokens[0],
    )


@app.get(
    "/debug/configs",
    include_in_schema=not settings.is_prod,
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
            configs = await fetch_user_configs_from_redis(user_email)
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
    include_in_schema=not settings.is_prod,
    dependencies=[Depends(HTTPBearer(auto_error=False))],
)
async def post_auth_debug(
    request: Request, check_request_in: CheckRequestIn
):  # pragma: no cover
    user_email = await fetch_user(request)
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
    top_x: int|None,
    username: str = Depends(fetch_current_username),
):
    result = {}    
    keys = MetricsType if key == MetricsType.ALL else [key]
    for _key in keys:
        if _key == MetricsType.ALL:
            continue

        metrics = redis.hgetall(_key)

        for a in metrics:
            metrics[a] = int(metrics[a])

        result[_key] = {k: metrics[k] for k in sorted(metrics, key=metrics.get, reverse=True)}
        if top_x is not None:
            result[_key] = {dkey:value for dkey,value in list(result[_key].items())[0:top_x]}

    if key != MetricsType.ALL:
        return result[key]

    return result


@app.post(
    "/v2.0/auth",
    response_model=Union[ResultConf, dict, None],
    response_model_exclude_none=True,
    dependencies=[Depends(HTTPBearer(auto_error=False))],
)
async def post_auth_2_0(request: Request, check_request_in: BaseRequestIn | None = None):
    client = parse_client(
        check_request_in.client if check_request_in is not None else None
    )
    check_client_version(client)

    user_email = await fetch_user(request)
    configs = await fetch_configs_for_request(CheckRequestIn(text=""), user_email) if user_email else {}

    store_metrics(request, configs, "2.0", 'auth')

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
    include_in_schema=not settings.is_prod,
    response_model=list[ResultOut],
    response_model_exclude_none=True,
)
async def post_debug_rule(
    rule_data: RuleIn,
    username: str = Depends(fetch_current_username),
):
    lang = Language(rule_data.lang)
    config = Config(plan="witty_teams")

    tokens = fetch_tokens(lang.lang, rule_data.text)
    for token in tokens:
        if token.text in rule_data.lemmatizations:
            token.lemma_ = rule_data.lemmatizations[token.text]

    offsets = utf16_offsets(rule_data.text)
    false_positive_matcher = fetch_false_positive_matchers(lang.lang, tokens)

    if rule_data.alternatives is not None:
        alternative_list = []
        for alternative_in in rule_data.alternatives:
            alternative = Alternative(
                alternative_in.lemma,
                tokenize(alternative_in.lemma, rule_data.lang),
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
        tokenize(rule_data.lemma, rule_data.lang),
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
    client = parse_client("debug:" + version)

    token_index = 0
    token_count = len(tokens)
    while token_index < token_count:
        if rule_data.lang == LangType.DE:
            tokens[token_index].lemma_ = await german_lemmatization(tokens, token_index)

        for rule in rules:
            await rule_check(
                config,
                client,
                lang,
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
    include_in_schema=not settings.is_prod,
    response_class=PrettyJSONResponse,
)
async def get_debug_spacy(
    text: str,
    lang: LangType,
    detailed: bool = False,
    username: str = Depends(fetch_current_username),
):
    results = []
    tokens = fetch_tokens(lang, text)

    word_type_rule = None
    for token_index in range(len(tokens)):
        token = tokens[token_index]
        if word_type_rule is None:
            word_type_rule = ""
        else:
            word_type_rule += "|"

        if lang == LangType.DE:
            token.lemma_ = await german_lemmatization(tokens, token_index)
        word_type = await fetch_word_type(lang, token)
        if token.text != token.lemma_:
            word_type_rule += "~"
        word_type_rule += word_type

        token_info = {
            "text": token.text,
            "lemma": token.lemma_,
            "word_type": word_type,
            "is_singular": is_token_singular(lang, token),
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
    username: str = Depends(fetch_current_username),
):
    return await german_noun_lookup(word)


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
    check_request_in: CheckRequestIn,
    username: str = Depends(fetch_current_username),
):
    return await check(request, response, check_request_in)


@app.post(
    "/v2.3/check",
    response_model=Union[ResultsOut, Result],
    response_model_exclude_none=True,
    dependencies=[Depends(HTTPBearer(auto_error=False))],
)
async def post_check_v2_3(
    request: Request,
    response: Response,
    check_request_in: CheckRequestIn,
):
    return await check(request, response, check_request_in, "2.3")


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
    status_code=status.HTTP_204_NO_CONTENT,
)
async def post_organization_configs(
    organization_configs: OrganizationConfRequest,
    username: str = Depends(fetch_current_username),
):
    organization_configs.term_replacements = parse_term_replacements(
        organization_configs.term_replacements
    )

    redis.set(organization_configs.id, organization_configs.model_dump_json())


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
    status_code=status.HTTP_204_NO_CONTENT,
)
async def post_user_configs(
    user_configs: UserConfRequest, username: str = Depends(fetch_current_username)
):
    user_configs.term_replacements = parse_term_replacements(
        user_configs.term_replacements
    )

    redis.set(get_user_id(user_configs.email), user_configs.model_dump_json())


@app.delete(
    "/user/configs",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_user_configs(
    email: str,
    username: str = Depends(fetch_current_username),
):
    redis.delete(get_user_id(email))


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


# Functions
def store_metrics(request: Request, configs: dict, version: str | None, endpoint: str):
    if not settings.log_metrics:
        return

    version = version + " - " if version is not None else "none - "

    if "id" in configs:
        user_id = configs["id"]
        plan = None if "plan" not in configs else configs["plan"]
        if (
            "organization_config" in configs
            and "trial_ends_at" in configs["organization_config"]
            and configs["organization_config"]["trial_ends_at"] is not None
        ):
            plan = "witty_trial"
    else:
        user_id = "none"
        plan = "none"

    host = request.headers.get("origin", "none")

    if endpoint == "auth":
        redis.hincrby(MetricsType.AUTH_COUNTS, version + user_id, 1)
        redis.hincrby(MetricsType.AUTH_PLANS, version + plan, 1)
        redis.hincrby(MetricsType.AUTH_HOST, version + host, 1)
    elif endpoint == "check":
        redis.hincrby(MetricsType.CHECK_COUNTS, version + user_id, 1)
        redis.hincrby(MetricsType.CHECK_PLANS, version + plan, 1)
        redis.hincrby(MetricsType.CHECK_HOST, version + host, 1)
    elif endpoint == "rephrase":
        redis.hincrby(MetricsType.REPHRASE_COUNTS, version + user_id, 1)
        redis.hincrby(MetricsType.REPHRASE_PLANS, version + plan, 1)
        redis.hincrby(MetricsType.REPHRASE_HOST, version + host, 1)

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

    if lemma.endswith("|en") or lemma.endswith("|de"):
        term_replacement["lang"] = lemma[-2:]
        term_replacement["lemma"] = lemma[0:-3]
    else:
        term_replacement["lang"] = None
        term_replacement["lemma"] = lemma

    term_replacement["words"] = tokenize(term_replacement["lemma"], lang)
    term_replacement["word_types"] = word_type * len(term_replacement["words"])

    term_replacement["false_positives"] = []
    term_replacement["parsed_alternatives"] = []
    for alternative in term_replacement["alternatives"]:
        term_replacement["false_positives"].append(alternative)

        alternative = {"lemma": alternative}
        alternative["words"] = tokenize(alternative["lemma"], lang)
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


async def fetch_organization_configs_from_redis(
    organization_id: str,
) -> dict:
    configs = redis.get(organization_id)
    if not configs:
        raise HTTPException(status_code=404, detail="Organization configs not found")

    return json.loads(configs)


async def fetch_user_configs_from_redis(
    email: str,
) -> dict:
    configs = redis.get(get_user_id(email))
    if not configs:
        raise HTTPException(status_code=404, detail="User configs not found")

    return json.loads(configs)


async def fetch_user_organization_configs(email: str) -> dict | None:
    configs = await fetch_user_configs_from_redis(email)

    configs["organization_name"] = None
    configs["organization_config_hash"] = None
    configs["organization_domains"] = None
    configs["organization_trial_ends_at"] = None

    if "organization_id" in configs and configs["organization_id"] is not None:
        organization_configs = await fetch_organization_configs_from_redis(
            configs["organization_id"]
        )

        if "plan" not in configs or configs["plan"] is None:
            configs["plan"] = organization_configs["plan"]

        if "trial_ends_at" in organization_configs:
            configs["organization_trial_ends_at"] = organization_configs["trial_ends_at"]

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


def is_token_singular(lang: LangType, token: Token) -> bool | None:
    plural_lookup_first = (
        False if token.text.endswith("e") and token.lemma_.endswith("er") else True
    )
    if plural_lookup_first and token.text in lemma_plural_lookup[lang]:
        return False

    number = token.morph.get("Number")
    if number:
        return "Sing" in number

    if not plural_lookup_first and token.text in lemma_plural_lookup[lang]:
        return False

    if lang == LangType.EN and token.pos == "NOUN" and token.text.endswith("s"):
        return False

    if token.text.endswith("-"):
        return False

    return None


def is_token_plural(lang: LangType, token: Token) -> bool | None:
    is_singular = is_token_singular(lang, token)
    if is_singular is None:
        return None

    return not is_singular


def apply_configs(
    check_request_in: CheckRequestIn, configs: dict, plan: str, force_disables: bool = True
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
        elif data["status"] == "force":
            check_request_in.config.__setattr__(config, data["value"])

    check_request_in.config.__setattr__("disabled_categories", disabled_categories)
    check_request_in.config.__setattr__("plan", plan)


async def fetch_configs_for_request(
    request_in: BaseRequestIn, user_email=Optional[str]
) -> dict:
    request_in.config.__setattr__("store_context", True)
    request_in.config.__setattr__("plan", None)
    request_in.config.__setattr__(
        "alternatives_max_count", settings.alternatives_max_count
    )

    if not user_email:
        request_in.config.__setattr__(
            "disabled_categories", get_category_keys(True)
        )
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

    if not organization_id:
        return {}

    try:
        configs = await fetch_organization_configs_from_redis(organization_id)
    except HTTPException:
        return {}

    for config in configs["configs"]:
        if configs["configs"][config]["status"] == "suggestion":
            configs["configs"][config]["status"] = "force"

    apply_configs(request_in, configs["config"], configs["plan"])

    return configs


def fetch_email_from_claims(claims: dict) -> str:
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


async def fetch_user(request: Request) -> str | None:
    if "authorization" in request.headers and request.headers[
        "authorization"
    ].lower().startswith("bearer"):
        try:
            unverified_claims = get_unverified_token_claims(request)
            for key in settings.sso_configs:
                config = settings.sso_configs[key]
                if (
                    "aud" not in unverified_claims
                    or unverified_claims["aud"] != config["client_id"]
                ):
                    continue

                if "domain" in config:
                    claims = await decode_b2c_jwt(
                        redis,
                        ssl_session,
                        request,
                        config["tenant_id"],
                        config["client_id"],
                        config["expected_scope"],
                        config["domain"],
                        config["policy"],
                    )
                elif "tid" in unverified_claims:
                    claims = await decode_jwt(
                        redis,
                        ssl_session,
                        request,
                        unverified_claims["tid"],
                        config["client_id"],
                        config["expected_scope"],
                    )

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


def fetch_text(
    check_request_in: CheckRequestIn, supported_langs: list
) -> tuple[str, Language | None, bool]:
    text = check_request_in.text
    limit_reached = len(text) > settings.text_max_length
    if limit_reached:
        text = text[0 : settings.text_max_length]
        text = text.rsplit(" ", 1)[0]

    lang_detection = get_lang_detection(fasttext_model)
    locale = lang_detection.get_locale(
        supported_langs,
        text,
        check_request_in.lang,
        check_request_in.config.preferred_languages,
        check_request_in.config.preferred_variants,
    )

    lang = None if locale is None else Language(locale)

    return text, lang, limit_reached

def rephrase_api_version(version: str):
    if version != "1.0":  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"API version '{version}' not supported, please use version '1.0'.",
        )


def check_api_version(version: str):
    if version != "2.3" and version != "2.4":  # pragma: no cover
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"API version '{version}' not supported, please use version '2.3' (deprecated) or '2.4'.",
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
    check_request_in: CheckRequestIn,
    version: str | None = None,
) -> Result | ResultsOut:
    client = parse_client(check_request_in.client)
    check_client_version(client)

    if version is not None:
        check_api_version(version)

        user_email = await fetch_user(request)
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

    store_metrics(request, configs, version, "check")

    if (
        check_request_in.config.plan is not None
        and check_request_in.config.plan.startswith("witty_")
    ):
        text, lang, limit_reached = fetch_text(check_request_in, model.keys())

        if lang is None:
            response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
            results = Result.factory("Language could not be determined")
            language = None
            configs = {}
        else:
            results = await apply_language_rules(
                client, check_request_in.config, configs, lang, text
            )

            language = lang.lang

        if isinstance(results, Result):
            return results
    else:
        results = []
        language = "en"
        limit_reached = False

    notifications = None
    if "notifications" in configs and configs["notifications"] > 0:
        notifications = configs["notifications"]

    has_consented_to_mailing = None
    if "has_consented_to_mailing" in configs:
        has_consented_to_mailing = configs["has_consented_to_mailing"]

    if version == "2.3":
        for result in results:
            for alternative in result.alternatives:
                alternative.type = None
                alternative.url = None

    return ResultsOut(
        results=results,
        language=language,
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


def fetch_alternatives(match: dict) -> list[Alternative]:
    alternatives = []
    if "replacements" in match:
        for replacement in match["replacements"]:
            value = replacement["value"]
            value = value if value != "" else "-"
            alternatives.append(Alternative(value))

    return alternatives


def has_gender_denom_ending(
    text: str, full_text: str, offset: int, config: Config
) -> bool:
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
    config: Config,
    client: Client,
    lang: Language,
    full_text: str,
    tokens: Doc,
    offsets: dict,
    matches: list,
) -> list:
    entities = []
    for ent in tokens.ents:
        entities.append(ent)

    list_results = []
    ignore = ["@", "#"]

    gendered_denom = lang.lang == LangType.DE and gendered_roles_format_inclusive(
        config.gendered_roles_format
    )

    for match in matches:
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
                    is_entity = (
                        entity.label_
                        in static_rules["named_entity_labels"][EntityType.NAME]
                    )
                    break

            if is_entity:
                continue

        # Ignore capitalization after salutation
        # TODO: Train NER to handle salutations better like "\n Hallo Konstantina\n\nWie geht es dir?"
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
                for substring in static_rules[lang.lang]["salutations"]
            ):
                continue

        if (
            lang.lang == LangType.DE
            and config.german_gender_ending == ":in"
            and match["rule"]["id"] == "LEERZEICHEN_HINTER_DOPPELPUNKT"
            and full_text[start + 1 : end]
            in static_rules[LangType.DE]["masculine_articles"]
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
            elif subcategory in lt_style_categories_plain_language:
                if (
                    subcategory == "STYLE"
                    and (
                        match["rule"]["id"]
                        in [
                            "TWITTER_X",
                            "SERIAL_COMMA_ON",
                        ]
                    )
                    or match["rule"]["id"].endswith("REPEAT_BEGINNING_RULE")
                ):
                    subcategory = "orthography"
                else:
                    subcategory = "plain_language"
            elif subcategory == "PLAIN_ENGLISH":
                subcategory = "plain_language_advanced"
            elif subcategory == "DIFFICULT_WORDS":
                if match["rule"]["id"] == "ABKUERZUNG":
                    continue

                if (
                    match["rule"]["id"] == "ANGLIZISMEN"
                    or "Fremdwörter" in match["message"]
                ):
                    subcategory = "anglicism_advanced"
                else:
                    subcategory = "plain_language_advanced"
            elif match["rule"]["category"]["name"] == "Leichte Sprache":
                subcategory = "plain_language_advanced"
            else:
                subcategory = subcategory.lower()
                if subcategory not in categories:
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

        if not subcategory.startswith("abbreviation") and not subcategory.startswith(
            "anglicism"
        ):
            explanation = match["message"]
        else:
            explanation = None

        list_results.append(
            ResultOut.factory(
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


async def handle_response(
    r: aiohttp.ClientResponse, name: str, json: bool = True
) -> any:
    try:
        if r.status != 200:  # pragma: no cover
            result = await r.text()
            logger.error(result)

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

        logger.error(result)

    return result


async def fetch_json_get(
    url: str,
    payload: any,
    headers: any,
    name: str,
    ssl: bool = True,
    json: bool = True,
) -> any:
    if ssl:
        async with ssl_session.get(url, params=payload, headers=headers) as r:
            return await handle_response(r, name, json)

    async with session.get(url, params=payload, headers=headers) as r:
        return await handle_response(r, name, json)


async def fetch_json_post(
    url: str,
    payload: any,
    headers: any,
    name: str,
    ssl: bool = True,
    json: bool = True,
) -> any:
    if ssl:
        async with ssl_session.post(url, data=payload, headers=headers) as r:
            return await handle_response(r, name, json)

    async with session.post(url, data=payload, headers=headers) as r:
        return await handle_response(r, name, json)


def convert_to_csv(payload: dict, key: str) -> dict:
    if len(payload[key]):
        payload[key] = ",".join(payload[key])
    else:
        del payload[key]

    return payload


async def apply_languagetool_rules(
    config: Config,
    client: Client,
    lang: Language,
    text: str,
    tokens: Doc,
    offsets: dict,
) -> list:
    if not settings.languagetool_api:
        return []

    payload = {
        "text": text,
        "language": lang.locale,
        "disabledCategories": [
            "GENDER_NEUTRALITY",  # Handled via Witty rules
        ],
        "enabledCategories": [],
        "disabledRules": [
            # Ignore case issues at the start of sentence due to chunking issues
            # https://github.com/witty-works/browser-extension/pull/880
            "UPPERCASE_SENTENCE_START",
            # Ignore "70%", "100km" needing a space between the unit
            "EINHEIT_LEERZEICHEN",
            # Ignore unpaired brackets like a)
            "EN_UNPAIRED_BRACKETS",
            "UNPAIRED_BRACKETS",
            # Profanity
            "PROFANITY_XML",
        ],
    }

    if payload["language"][0:2] == LangType.EN and is_sub_category_enabled(
        config, "plain_language"
    ):
        payload["level"] = "picky"

    if is_sub_category_enabled(config, "plain_language_advanced"):
        if payload["language"] == LangVariantType.deDE:
            payload["language"] += "-x-simple-language"

        if payload["language"][0:2] == LangType.EN:
            payload["enabledCategories"].append("PLAIN_ENGLISH")
    else:
        payload["disabledCategories"].append("PLAIN_ENGLISH")

    if config.primary_language is not None:
        payload["motherTongue"] = config.primary_language

    if is_sub_category_enabled(config, "orthography"):
        if "casing" in config.disabled_categories:
            payload["disabledCategories"].append("CASING")

        if "plain_language" in config.disabled_categories:
            payload["disabledCategories"] += lt_style_categories_plain_language
    elif is_sub_category_enabled(config, "plain_language"):
        payload["enabledCategories"] += lt_style_categories_plain_language
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

    if (
        not isinstance(result, dict)
        or "matches" not in result
        or len(result["matches"]) == 0
    ):
        return []

    return languagetool_matches(
        config, client, lang, text, tokens, offsets, result["matches"]
    )


def utf16len(c: str) -> int:
    """Returns the length of the single character 'c'
    in UTF-16 code units."""
    return 1 if ord(c) < 65536 else 2


def fetch_tokens(lang: LangType, text: str) -> Doc:
    return model[lang](text.rstrip().replace("\n", " "))


def utf16_offsets(text: str) -> dict:
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
def is_false_positive_match(
    false_positive_matcher: list, token_index: int, tokens: Doc, lemma: str
) -> bool:
    index = tokens[token_index].idx
    for _, start, end in false_positive_matcher:
        span_false = tokens[start:end]
        if tokens[start:end].lemma_ != lemma and index in range(
            span_false.start_char, span_false.end_char
        ):
            return True

    return False


# create false positives patterns based on false positives column
def fetch_false_positive_matcher(
    lang: LangType, tokens: Doc, false_positives: list
) -> list:
    if len(false_positives) == 0:
        return []

    matcher = Matcher(model[lang].vocab)

    for false_positive in false_positives:
        matcher.add("FalsePositivesList", false_positive)

    return matcher(tokens)


def fetch_phrase_matcher(lang: LangType, tokens: Doc, phrases: list) -> list:
    # Phrase matcher part to handle False positives with two words and special symbols
    matcher = PhraseMatcher(model[lang].vocab, attr="LOWER")

    # Only run model.make_doc to speed things up
    patterns = [model[lang].make_doc(text) for text in phrases]
    matcher.add("TerminologyList", patterns)

    return matcher(tokens)


def fetch_false_positive_matchers(lang: LangType, tokens: Doc) -> list:
    return fetch_false_positive_matcher(
        lang, tokens, static_rules[lang]["pattern_false_positives"]
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
    lang: Language,
    text: str,
) -> list:
    tokens = fetch_tokens(lang.lang, text)
    offsets = utf16_offsets(text)

    term_replacements = fetch_term_replacements(configs, lang.lang)

    match lang.lang:
        case LangType.DE:
            list_results = await german_rules(
                config,
                term_replacements,
                client,
                tokens,
                offsets,
                lang,
                text,
            )
        case LangType.EN:
            list_results = await english_rules(
                config,
                term_replacements,
                client,
                tokens,
                offsets,
                lang,
                text,
            )
        case LangType.FR:
            # TODO implement french_rules()
            list_results = await english_rules(
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
        config, client, lang, text, tokens, offsets
    ) + await context_false_positives(lang.lang, tokens, list_results)

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


def is_sub_category_enabled(config: Config, subcategories: list[str]) -> bool | str:
    if isinstance(subcategories, str):
        subcategories = [subcategories]

    for subcategory in subcategories:
        if subcategory in config.disabled_categories:
            continue

        category_data = get_category(subcategory)
        if category_data is None:
            continue

        if (
            "category" in category_data
            and category_data["category"] in config.disabled_categories
        ):
            continue

        return subcategory

    return False


def is_gendered_denom_rule(lang: LangType, subcategories) -> bool:
    if lang != LangType.DE:
        return False

    if isinstance(subcategories, str):
        return get_category_name(subcategories) in [
            "titles",
            "function",
            "gender_identity",
            "hidden_image",
            "leadership",
            "male_stereotype",
            "female_stereotype",
            "gendered_denominations_ending",
        ]

    for subcategory in subcategories:
        if is_gendered_denom_rule(lang, subcategory):
            return True

    return False


async def context_false_positives(
    lang: LangType, tokens: Doc, list_results: list[ResultOut]
):
    if (
        lang not in settings.context_checker
        or len(static_rules[lang]["context_check"]) == 0
    ):
        return list_results

    sentences = {}
    sentences_to_check = defaultdict(list)
    for result_index in range(len(list_results)):
        result = list_results[result_index]
        if result.text_id in static_rules[lang]["context_check"]:
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

        logger.error(
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


async def fetch_rules(
    lang: LangType,
    token: Token,
    text: str,
    lemma: str,
    addons: list[str],
    suffix_check: bool = False,
    rewrite_to: str|None = None,
) -> list[Rule]:
    female_lemma_filter = None

    if suffix_check:
        upper_char_count = sum(1 for c in text if c.isupper())
        # Elite-Partner (match) vs. ElitePartner (name -> ignore)
        if upper_char_count > 1 and text.count("-") < upper_char_count - 1:
            return []

        first_token_check = "first_token LIKE ?"
        text_filter = "%" + text[-4:]
        lemma_filter = "%" + lemma[-4:]
    else:
        first_token_check = "first_token = ?"
        text_filter = text
        lemma_filter = lemma

        if lemma in male_to_female_normativ:
            female_lemma_filter = male_to_female_normativ[lemma]

    token_filter_lower = text_filter.lower()
    lemma_filter_lower = lemma_filter.lower()

    if text == lemma:
        if token_filter_lower == text_filter:
            filters = {
                first_token_check: text_filter,
            }
        else:
            filters = {
                f"({first_token_check} and first_is_word_type_lower_case = 1)": token_filter_lower,
                f"({first_token_check} and first_is_word_type_lower_case = 0)": text_filter,
            }
    else:
        if text_filter == token_filter_lower:
            filters = {
                f"({first_token_check} AND first_is_word_type_lemmatize = 0)": text_filter,
            }
        else:
            filters = {
                f"({first_token_check} AND first_is_word_type_lemmatize = 0 AND first_is_word_type_lower_case = 1)": token_filter_lower,
                f"({first_token_check} AND first_is_word_type_lemmatize = 0 AND first_is_word_type_lower_case = 0)": text_filter,
            }

        if lemma_filter == lemma_filter_lower:
            filters[f"({first_token_check} AND first_is_word_type_lemmatize = 1)"] = (
                lemma_filter
            )
        else:
            filters[
                f"({first_token_check} AND first_is_word_type_lemmatize = 1 AND first_is_word_type_lower_case = 1)"
            ] = lemma_filter_lower
            filters[
                f"({first_token_check} AND first_is_word_type_lemmatize = 1 AND first_is_word_type_lower_case = 0)"
            ] = lemma_filter

    if female_lemma_filter is not None:
        filters[
            f"({first_token_check} AND first_is_word_type_lemmatize = 1)"
        ] = female_lemma_filter.lower()

    query = f"SELECT {rule_column_list} FROM rules_rule WHERE language = ? AND type = ? AND diversity_dimension_json != '[]'"
    if addons is not None and "hr" not in addons:
        query += " AND is_hr_rule = 0"

    filter_list = " OR ".join(filters.keys())
    query += f" AND ({filter_list}) ORDER BY lemma_length DESC, first_is_word_type_lemmatize ASC"
    parameters = [lang, RuleType.SUFFIX if suffix_check else RuleType.DEFAULT] + list(
        filters.values()
    )

    is_gender_star_ending_ = False
    rows = await fetch_rows(query, parameters)
    if lang == LangType.EN:
        if rewrite_to is None and len(rows) == 0:
            rewrite_to = "en-US"
            us_text = Language.convert_to(text, rewrite_to)
            if us_text != text:
                return await fetch_rules(
                    lang,
                    token,
                    us_text,
                    Language.convert_to(lemma, rewrite_to),
                    addons,
                    suffix_check,
                    "en-US",
                )
    elif lang == LangType.DE:
        is_gender_star_ending_ = is_gender_star_ending(token.text)
        if not suffix_check and is_gender_star_ending_ and len(rows) == 0:
            new_text = is_gender_star_ending_[1] + is_gender_star_ending_[2]
            if new_text != text:
                rules = await fetch_rules(lang, token, new_text, new_text, addons)
                if len(rules):
                    token.lemma_ = new_text

                return rules

    rules = []
    for row in rows:
        rule = create_rule(lang, row, rewrite_to)
        if is_gender_star_ending_ and is_gendered_denom_rule(lang, rule.subcategories):
            continue
        rules.append(rule)

    if suffix_check:
        text_lower = token.text.lower()
        for substring in substring_rules[lang]:
            if substring in text_lower:
                rules.append(substring_rules[lang][substring])

    return rules


async def fetch_rule_alternatives(
    client: Client,
    rule: Rule,
    is_singular: bool | None,
    show_inspiration_alternatives: bool,
    locale: str,
) -> list[Alternative]:
    if isinstance(rule.id, str):
        return rule.alternatives

    query = f"SELECT {alternative_column_list} FROM rules_alternative WHERE rule_id = ?"

    parameters = [rule.parent_id if rule.parent_id else rule.id]

    if not show_inspiration_alternatives:
        query += " and is_inspiration = 0"
        query += " and is_placeholder = 0"

    # TODO ignore pluralization for inspirations?
    if is_singular is not None:
        query += " and pluralization != ?"
        parameters.append("plural_only" if is_singular else "singular_only")

    query += " ORDER BY `order` ASC"

    alternatives = []
    rows = await fetch_rows(query, parameters)
    if len(rows) == 0:
        if not show_inspiration_alternatives:
            return await fetch_rule_alternatives(
                client, rule, is_singular, True, locale
            )
        if is_singular is not None:
            return await fetch_rule_alternatives(client, rule, None, True, locale)

    for row in rows:
        lemma = row[alternative_columns["lemma"]]
        # remove until we can properly handle this in the UI
        # https://www.notion.so/witty-works/Rule-Guidelines-432792da944141b1b4d0a01de290aa43#9ab16aeb0c19416ca0b72fde152b5d86
        if "^" in lemma:
            continue

        if row[alternative_columns["is_remove"]]:
            lemma = None
            lemma_json = ()
            word_types_json = ()
        else:
            lemma_json = json.loads(row[alternative_columns["lemma_json"]])
            word_types_json = json.loads(row[alternative_columns["word_types_json"]])

        if lemma and locale == LangVariantType.enGB:
            lemma = Language.convert_to(lemma, locale)
            lemma_json = Language.convert_to(lemma_json, locale)

        alternative = Alternative(
            lemma,
            lemma_json,
            word_types_json,
            row[alternative_columns["is_remove"]],
            row[alternative_columns["is_inspiration"]],
            row[alternative_columns["is_placeholder"]],
            row[alternative_columns["is_advanced"]],
            row[alternative_columns["is_collective_noun"]],
            row[alternative_columns["is_gendered_noun"]],
            row[alternative_columns["label"]],
        )

        if row[alternative_columns["type"]] == AlternativeType.DEFAULT:
            alternative.type = AlternativeType.DEFAULT
        elif row[alternative_columns["type"]] == AlternativeType.PERSON_FIRST:
            alternative.type = AlternativeType.PERSON_FIRST
        elif row[alternative_columns["type"]] == AlternativeType.IDENTITY_FIRST:
            alternative.type = AlternativeType.IDENTITY_FIRST

        alternatives.append(alternative)

    return alternatives


def is_valid_text(text: str) -> bool:
    if text == "(":
        return True

    return any(c.isalnum() for c in text)


def get_target_declension_form(target_result: dict, target_form: str):
    if target_result is None or target_form not in target_result:
        return None

    if target_result[target_form] is None or target_result[target_form] == "":
        return target_result["base_form"]

    return target_result[target_form]


async def fetch_declensions(
    lang: LangType,
    word_type: BasicWordType,
    text: str,
    token: Token|None = None,
) -> dict | None:
    if lang == LangType.FR:
        return None

    if token is not None and token._.forms is not None:
        return token._.forms

    text = (
        upperfirst(text)
        if lang == LangType.DE and word_type == BasicWordType.NOUN
        else text.lower()
    )

    columns = declensions_config[lang][word_type]["columns"]
    column_list = ", ".join(columns)
    table_name = declensions_config[lang][word_type]["name"]

    filters = []
    parameters = []
    for column in columns:
        if column in [
            "is_absolute",
            "gender_1",
            "gender_2",
            "collective_noun",
            "collective_noun_2",
            "female_form",
            "male_form",
            "helping_verb",
        ]:
            continue

        filters.append(f"{column} = ? COLLATE NOCASE")
        parameters.append(text)

    parameters.append(text)
    filter_list = " OR ".join(filters)

    query = f"SELECT {column_list} FROM {table_name} WHERE {filter_list} ORDER BY IIF(base_form = ?, 1, 0) DESC, LENGTH(base_form) DESC LIMIT 1"

    rows = await fetch_rows(query, parameters)

    forms = None if len(rows) == 0 else dict(zip(columns, rows[0]))
    if token is not None:
        token._.forms = forms

    return forms


def is_gender_star_ending(text: str) -> bool | re.Match:
    for regexp in Config._gendereddenom_ending.default:
        match = re.search(Config._gendereddenom_ending.default[regexp], text)
        if match:
            return match

    return False


def remove_gender_ending(text: str) -> str:
    if text[0].islower():
        return text

    if text.endswith("-"):
        ending = "s-" if text.endswith("s-") else "-"
        text = text.removesuffix(ending)

    match = is_gender_star_ending(text)
    if match:
        text = match[1] + match[2]

    return text


async def german_lemmatization(tokens: Doc, token_index: int):
    token = tokens[token_index]
    word_type = await fetch_word_type(LangType.DE, token)

    match word_type:
        case WordType.NOUN:
            if (
                token.text != token.lemma_
                or not token.text[0].isupper()
                or len(token.text) <= 3
            ):
                return token.lemma_

            word = remove_gender_ending(token.text)

            result = await german_noun_lookup(word, token)
            if result is not None:
                target = "male_form" if result["male_form"] else "base_form"
                return result[target]
        case WordType.VERB:
            verb_form = token.morph.get("VerbForm")
            verb_form = verb_form[0] if len(verb_form) else ""

            if verb_form not in verb_form_map:
                return token.lemma_

            column_name = False
            if isinstance(verb_form_map[verb_form], dict):
                tense = token.morph.get("Tense")
                tense = tense[0] if len(tense) else ""
                person = token.morph.get("Person")
                person = person[0] if len(person) else ""

                if (
                    tense in verb_form_map[verb_form]
                    and person in verb_form_map[verb_form][tense]
                ):
                    parameters = [token.text + "%"]
                    operator = "LIKE"
                    column_name = verb_form_map[verb_form][tense][person]
            else:
                if token_index > 0 and tokens[token_index - 1].text == "zu":
                    parameters = ["zu " + token.text]
                    prev = True
                else:
                    parameters = [token.text]
                    prev = False
                operator = "="
                column_name = verb_form_map[verb_form]

            if column_name:
                table_name = declensions_config[LangType.DE][WordType.VERB]["name"]
                query = f"SELECT base_form, {column_name} FROM {table_name} WHERE {column_name} {operator} ? LIMIT 1"

                rows = await fetch_rows(query, parameters)
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

                                    await fetch_declensions(
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

                    await fetch_declensions(LangType.DE, WordType.VERB, rows[0][0])
                    return rows[0][0]

    return token.lemma_


async def german_rules(
    config: Config,
    term_replacements: list[Rule],
    client: Client,
    tokens: Doc,
    offsets: dict,
    lang: Language,
    text: str,
) -> list:
    list_full = []

    token_index = new_token_index = 0
    token_count = len(tokens)
    while new_token_index < token_count:
        token_index = new_token_index

        token = tokens[token_index]
        if token._.connected_token is not None:
            new_token_index += 1
            continue

        token.lemma_ = await german_lemmatization(tokens, token_index)

        if len(term_replacements):
            new_token_index = await rule_check(
                config,
                client,
                lang,
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

        if is_sub_category_enabled(config, "gender_specific_abbreviation"):
            new_token_index = await regex_match(
                config,
                client,
                lang,
                text,
                token_index,
                tokens,
                offsets,
                list_full,
                static_rules["m_f_regexes"],
            )

            if check_continue(
                list_full, token_index, new_token_index, tokens, "regex_match"
            ):
                continue

        new_token_index = detect_non_inclusive_emoji(
            config,
            client,
            lang,
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
            new_token_index = await regex_match(
                config,
                client,
                lang,
                text,
                token_index,
                tokens,
                offsets,
                list_full,
                static_rules[LangType.DE]["hashtags"],
            )

            if check_continue(
                list_full, token_index, new_token_index, tokens, "regex_match"
            ):
                continue

        if is_valid_text(token_text) and len(token_text) > 1:
            new_token_index = await rule_check(
                config,
                client,
                lang,
                text,
                token_index,
                tokens,
                offsets,
                list_full,
                await fetch_rules(
                    lang.lang,
                    token,
                    token.text,
                    token.lemma_,
                    config.addons,
                ),
            )

            if check_continue(
                list_full, token_index, new_token_index, tokens, "rule_check"
            ):
                continue

            new_token_index = await rule_check(
                config,
                client,
                lang,
                text,
                token_index,
                tokens,
                offsets,
                list_full,
                await fetch_rules(
                    lang.lang,
                    token,
                    token.text,
                    token.lemma_,
                    config.addons,
                    True,
                ),
            )

            if check_continue(
                list_full, token_index, new_token_index, tokens, "rule_check"
            ):
                continue

        subcategory = "d_and_i"
        if is_sub_category_enabled(config, subcategory):
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
                        config._gendereddenom_ending_article[
                            config.german_gender_ending
                        ],
                        None,
                        word_types,
                        subcategory,
                    )
                )

            new_token_index = await regex_match(
                config,
                client,
                lang,
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
                continue

        subcategory = "gendered_denominations_ending_advanced"
        if is_sub_category_enabled(
            config, subcategory
        ) and gendered_roles_format_inclusive(config.gendered_roles_format):
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
                    word_types = (
                        (-1, 2, key[0]) if key[0] == "/" else (None, None, key[0])
                    )

                    ending = Rule(
                        key + "article",
                        LangType.DE,
                        config._gendereddenom_ending_article[key],
                        None,
                        word_types,
                        subcategory,
                    )

                    endings.append(ending)

            new_token_index = await regex_match(
                config,
                client,
                lang,
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
                continue

        new_token_index += 1

    return list_full


async def english_rules(
    config: Config,
    term_replacements: list[Rule],
    client: Client,
    tokens: Doc,
    offsets: dict,
    lang: Language,
    text: str,
) -> list:
    false_positive_matcher = fetch_false_positive_matchers(lang.lang, tokens)

    list_full = []
    token_index = new_token_index = 0
    token_count = len(tokens)
    while new_token_index < token_count:
        token_index = new_token_index

        token = tokens[token_index]
        if token._.connected_token is not None:
            new_token_index += 1
            continue

        if len(term_replacements):
            new_token_index = await rule_check(
                config,
                client,
                lang,
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

        if is_sub_category_enabled(config, "gender_specific_abbreviation"):
            new_token_index = await regex_match(
                config,
                client,
                lang,
                text,
                token_index,
                tokens,
                offsets,
                list_full,
                static_rules["m_f_regexes"],
            )

            if check_continue(
                list_full, token_index, new_token_index, tokens, "regex_match"
            ):
                continue

        new_token_index = detect_non_inclusive_emoji(
            config,
            client,
            lang,
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
            new_token_index = await regex_match(
                config,
                client,
                lang,
                text,
                token_index,
                tokens,
                offsets,
                list_full,
                static_rules[LangType.EN]["hashtags"],
            )

            if check_continue(
                list_full, token_index, new_token_index, tokens, "regex_match"
            ):
                continue

        if not is_valid_text(token_text) or (
            len(token_text) <= 1 or token_text.lower() == "i"
        ):
            new_token_index += 1
            continue

        new_token_index = await rule_check(
            config,
            client,
            lang,
            text,
            token_index,
            tokens,
            offsets,
            list_full,
            await fetch_rules(
                lang.lang,
                token,
                token.text,
                token.lemma_,
                config.addons,
            ),
            false_positive_matcher,
        )

        if check_continue(
            list_full, token_index, new_token_index, tokens, "rule_check"
        ):
            continue

        new_token_index = await rule_check(
            config,
            client,
            lang,
            text,
            token_index,
            tokens,
            offsets,
            list_full,
            await fetch_rules(
                lang.lang,
                token,
                token.text,
                token.lemma_,
                config.addons,
                True,
            ),
            false_positive_matcher,
        )

        if check_continue(
            list_full, token_index, new_token_index, tokens, "rule_check"
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


async def check_pattern(
    tokens: Doc, pattern: str, i_pattern_start: int, offset: int
) -> bool | int:
    count = 0
    for word_type in pattern:
        allow_skip = word_type.endswith("*")
        if i_pattern_start < 0:
            return False

        if i_pattern_start >= len(tokens):
            if allow_skip:
                continue

            return False

        if allow_skip:
            word_type = word_type.removesuffix("*")
            while i_pattern_start >= 0 and await check_word_type(
                lang, tokens[i_pattern_start], word_type, True, True
            ):
                i_pattern_start -= 1
                count += 1
        elif await check_word_type(lang, tokens[i_pattern_start], word_type, True):
            i_pattern_start += offset
            count += 1
        else:
            return False

    return count


async def is_word_match(
    lang: LangType,
    token: Token,
    word: str,
    word_type: dict | None,
    suffix: str,
    lemma: str | None = None,
) -> bool:
    if word_type is None:
        word_type = {
            "word_type": "",
            "lemmatize": True,
            "lower_case": True,
        }

    lemma_ = token.lemma_ if lemma is None else lemma
    token_word = lemma_ if word_type["lemmatize"] else token.text

    # ignore differences between ’ and '
    token_word = token_word.replace("’", "'")
    word = word.replace("’", "'")

    if word_type["lower_case"]:
        token_word = token_word.lower()
        word = word.lower()

    if token_word != word and (
        not suffix or not token_word.lower().endswith(word.lower())
    ):
        if lemma is None and word_type["lemmatize"] and lemma_ in male_to_female_normativ:
            return await is_word_match(
                lang,
                token,
                word,
                word_type,
                suffix,
                male_to_female_normativ[lemma_]
            )
        return False

    return await check_word_type(lang, token, word_type["word_type"], True)


async def is_phrase_match(
    lang: LangType,
    token_index: int,
    tokens: Doc,
    rule: Rule,
    false_positive_matcher: list|None = None,
) -> tuple[int | None, str | None]:
    suffix = rule.type == RuleType.SUFFIX

    word_count = len(rule.words)
    word_types_count = len(rule.word_types)
    if word_count > 1:
        suffix = False

    skip_token_index = token_index
    text = ""
    for word_index in range(word_count):
        if word_index > 0:
            text += word_token.whitespace_

        try:
            word_token = tokens[token_index + word_index]
        except IndexError:
            return None, None

        word_type = (
            rule.word_types[word_index] if word_index < word_types_count else None
        )

        if not await is_word_match(
            lang,
            word_token,
            rule.words[word_index],
            word_type,
            suffix,
        ):
            return None, None

        text += word_token.text

        skip_token_index += 1

    if false_positive_matcher is not None and is_false_positive_match(
        false_positive_matcher, token_index, tokens, rule.lemma
    ):
        return None, None

    if rule.pattern is not None:
        pattern = rule.pattern.split("|")
        if pattern[0] == "*" or pattern[-1] == "*":
            logger.error(
                "Rule pattern may not start or end with '*' but is '%s', rule id %i, idx: '%s'",
                rule.pattern,
                rule.id,
                tokens[token_index].idx,
            )

            return None, None

        token_count = word_count
        prefix_tokens_match_count = 0
        lemma_position = pattern.index("l")

        if lemma_position > 0:
            prefix_pattern = pattern[0:lemma_position]
            prefix_pattern.reverse()
            tokens_match_count = await check_pattern(
                tokens, prefix_pattern, token_index - 1, -1
            )
            if not tokens_match_count:
                return None, None

            prefix_tokens_match_count += tokens_match_count

        suffix_pattern = pattern[lemma_position + 1 :]
        if len(suffix_pattern):
            tokens_match_count = await check_pattern(
                tokens, suffix_pattern, token_index + token_count, 1
            )
            if not tokens_match_count:
                return None, None

            token_count += tokens_match_count

        if rule.is_pattern_match:
            token_index -= prefix_tokens_match_count
            text = ""
            for k in range(prefix_tokens_match_count + token_count):
                if k > 0:
                    text += tokens[token_index + k - 1].whitespace_

                text += tokens[token_index + k].text

            skip_token_index = token_index + token_count + 1

    if token_index + tokens[token_index]._.token_index_offset > skip_token_index:
        skip_token_index = token_index + tokens[token_index]._.token_index_offset

    return skip_token_index, text


async def fetch_word_type(
    lang: LangType,
    token: Token,
    word_type: str|None = None,
    single_word: bool = False,
    strict: bool = False,
) -> str:
    if word_type is None and single_word == False and strict == False:
        cache = True
        if token._.word_type is not None:
            return token._.word_type
    else:
        cache = False

    word_type = await _fetch_word_type(
        lang,
        token,
        word_type,
        single_word,
        strict,
    )

    if cache:
        token._.word_type = word_type

    return word_type


async def _fetch_word_type(
    lang: LangType,
    token: Token,
    expected_word_type: str|None = None,
    single_word: bool = False,
    strict: bool = False,
) -> str:
    # https://machinelearningknowledge.ai/tutorial-on-spacy-part-of-speech-pos-tagging/
    # https://github.com/explosion/spaCy/blob/master/spacy/glossary.py

    if token._.is_emoji:
        return WordType.EMOJI

    if token.pos_ == "NUM":
        if WordType.NUMBER != expected_word_type and token.tag_ in ["CARD", "CD"]:
            return WordType.CARDINAL

        return WordType.NUMBER

    if not is_valid_text(token.text):
        return ""

    if expected_word_type is None:
        expected_word_type = ""

    if "adv" == expected_word_type and token.pos_ == "ADV":
        return WordType.ADVERB

    if (
        lang == LangType.EN
        and "-" in token.text
        and not token.text.startswith("-")
        and not token.text.endswith("-")
    ):
        tokens = fetch_tokens(lang, token.text.replace("-", " "))
        word_type = await fetch_word_type(
            lang, tokens[0], expected_word_type, single_word
        )
        # Case: "one-eyed" => "one eyed"
        if word_type in [
            WordType.CARDINAL,
            WordType.NUMBER,
        ] and expected_word_type not in [WordType.CARDINAL, WordType.NUMBER]:
            return await fetch_word_type(
                lang, tokens[-1], expected_word_type, single_word
            )

        return word_type

    if token.pos_ == "VERB":
        if (
            not strict
            and lang == LangType.DE
            and WordType.ADJECTIVE in expected_word_type
        ):
            return WordType.ADJECTIVE

        return WordType.VERB

    if token.tag_ in adj_tags or token.pos_ in adj_tags:
        return WordType.ADJECTIVE

    if token.pos_ in pronoun_tags or token.tag_ in pronoun_tags:
        if expected_word_type == WordType.NOUN:
            return WordType.NOUN

        return WordType.PRONOUN

    if token.pos_ == "NOUN" or token.tag_ == "NN":
        if lang == LangType.DE:
            if token.text[0].islower():
                result = await fetch_declensions(
                    LangType.DE, WordType.VERB, token.text, token
                )
                if result is not None:
                    return WordType.VERB

        return WordType.NOUN

    if lang == LangType.DE and token.text[0].isupper() and token.text.endswith("-"):
        return WordType.NOUN

    if token.tag_ == "KON" or token.pos_ == "CCONJ":
        return WordType.CONJUNCTION

    if token.pos_ == "PROPN":
        return expected_word_type

    return ""


async def check_word_type(
    lang: LangType,
    token: Token,
    word_type: str = "",
    single_word: bool|None = None,
    strict: bool = False,
) -> bool:
    if len(word_type) == 0:
        return True

    return word_type == await fetch_word_type(
        lang, token, word_type, single_word, strict
    )


def find_common_prefix(
    text1: str, text2: str, lower: bool = True, ignore_umlauts: bool = True
) -> str:
    prefix = text1

    if text1.lower().count("ä") != text2.lower().count("ä"):
        return ""

    if ignore_umlauts:
        prefix = prefix.replace("ä", "a").replace("ö", "o").replace("ü", "u")
    if lower:
        prefix = prefix.lower()

    if ignore_umlauts:
        text2 = text2.replace("ä", "a").replace("ö", "o").replace("ü", "u")

    while text2[: len(prefix)] != prefix and prefix:
        prefix = prefix[: len(prefix) - 1]
        if not prefix:
            break

    return prefix


def determine_gender_from_ending(word: str, german_gender_endings: list) -> str | None:
    for gender in german_gender_endings:
        for ending in german_gender_endings[gender]:
            if word.endswith(ending):
                return gender

    return None


async def german_noun_gender_lookup(word: str) -> str:
    if word.endswith("leute") or word.endswith("kraft") or word.endswith("person"):
        return "feminine"

    result = await german_noun_lookup(word)
    if result is None:
        gender = determine_gender_from_ending(
            word, static_rules[LangType.DE]["primary_german_gender_endings"]
        )

        if gender is None:
            gender = determine_gender_from_ending(
                word, static_rules[LangType.DE]["secondary_german_gender_endings"]
            )

        return gender

    return result["gender_1"]


def upperfirst(x: str):
    return x[0].upper() + x[1:]


async def german_noun_lookup(
    text: str, token: Token | None = None, prefix: str | None = None
) -> dict:
    word = text
    forms = await fetch_declensions(LangType.DE, WordType.NOUN, word, token)
    if forms is not None:
        return forms

    if word.endswith("-"):
        postfix = "s-" if word.endswith("s-") else "-"
        word = word[0 : -1 * len(postfix)]
        forms = await fetch_declensions(LangType.DE, WordType.NOUN, word, token)
    else:
        postfix = ""

    lower = False
    if prefix is None:
        prefix = ""

    if forms is None:
        if prefix != "":
            word = upperfirst(word.removeprefix(prefix))
            lower = not prefix.endswith("-")
            forms = await fetch_declensions(LangType.DE, WordType.NOUN, word, token)

        if forms is None:
            if "-" in word:
                words = word.split("-")
                word = words[-1]
                forms = await fetch_declensions(LangType.DE, WordType.NOUN, word, token)
                prefix = "-".join(words[0:-1]) + "-"
            else:
                lower = True
                prefix = ""

            while len(word) > 3 and forms is None:
                words = static_rules[LangType.DE]["german_nouns"].parse_compound(word)
                if len(words) == 0:
                    for substring in static_rules[LangType.DE][
                        "german_nouns_postfix"
                    ]:
                        position = text.find(substring)
                        if position >= 0:
                            words = [text[0:position], upperfirst(text[position:])]
                            break

                    if len(words) == 0:
                        break

                # Konzernverantwortlicher gets split into 'Konzern' + 'Verantwortliche'
                if len(words[-1]) > 3 and word[-1] != words[-1][-1]:
                    forms = await fetch_declensions(LangType.DE, WordType.NOUN, words[-1] + word[-1], token)

                if forms is None:
                    word = words[-1]
                    forms = await fetch_declensions(LangType.DE, WordType.NOUN, word, token)
                    if forms is None and len(words) > 2:
                        word = words[-2] + words[-1].lower()
                        forms = await fetch_declensions(
                            LangType.DE, WordType.NOUN, word, token
                        )

                if forms is not None:
                    for form in forms:
                        if forms[form] is None:
                            continue

                        ending_lower = forms[form].lower()
                        if text.endswith(ending_lower + postfix):
                            lower = True
                            prefix += text.removesuffix(ending_lower + postfix)
                            break

    if forms is None or (prefix == "" and postfix == ""):
        return forms

    for form in forms:
        if not form.startswith("gender") and forms[form] is not None:
            forms[form] = (
                prefix + (forms[form].lower() if lower else forms[form]) + postfix
            )

    return forms


def fetch_case(token: Token) -> str | None:
    match token.morph.get("Case"):
        case ["Dat"]:
            return "dativ"
        case ["Gen"]:
            return "genitiv"
        case ["Nom"]:
            return "nominativ"
        case ["Acc"]:
            return "akkusativ"

    return None


def fetch_flexion(token: Token) -> str | None:
    flexion = fetch_case(token)
    if flexion is None:
        return None

    flexion += " singular" if token.morph.get("Number") == ["Sing"] else " plural"

    return flexion


async def find_form_verb_german(token_index: int, tokens: Doc):
    token = tokens[token_index]
    if token._.form is not None:
        return token._.form

    forms = await fetch_declensions(LangType.DE, WordType.VERB, token.text, token)
    if forms is None:
        logger.error(
            f"German verb form could not be determined for '{token.text}' (lemma: '{token.lemma_}', idx: '{token.idx}')."
        )

        return None

    target_form = find_matching_form(forms, token.text)
    if (
        target_form is None
        and settings.log_missing_declension
        and check_word_case(token.text, False)
    ):
        logger.error(
            f"German verb target form could not be determined for '{token.text}' (lemma: '{token.lemma_}', idx: '{token.idx}')."
        )

    return target_form


async def find_form_verb_english(token_index: int, tokens: Doc):
    token = tokens[token_index]
    forms = await fetch_declensions(LangType.EN, WordType.VERB, token.text, token)

    if forms is not None:
        target_form = find_matching_form(forms, token.text)
        if target_form is not None:
            return target_form

    # Fallback code
    verb = Verb(token.text)
    if verb.is_singular():
        target_form = "third_person_singular"
    elif verb.is_past():
        target_form = "past_tense"
    elif verb.is_pres_part():
        target_form = "present_participle"
    elif verb.is_past_part():
        target_form = "past_participle"
    else:
        target_form = None

    if (
        target_form is None
        and settings.log_missing_declension
        and check_word_case(token.text, False)
    ):
        logger.error(
            f"English verb target form could not be determined for '{token.text}' (lemma: '{token.lemma_}', idx: '{token.idx}')."
        )

    return target_form


async def find_form_adjective_german(token_index: int, tokens: Doc):
    token = tokens[token_index]
    forms = await fetch_declensions(LangType.DE, WordType.ADJECTIVE, token.text, token)

    if forms is not None and forms["is_absolute"] == False:
        target_form = find_matching_form(forms, token.text)

        if target_form is not None:
            return target_form

    if len(token.text) < 2:
        ending = ""
    elif token.text.endswith("sten"):
        ending = "sten"
    elif token.text.endswith("ste"):
        ending = "ste"
    else:
        ending = token.text[-2:]
        if ending[0] != "e":
            ending = ending[1:]

    return ending


async def find_form_adjective_english(token_index: int, tokens: Doc):
    token = tokens[token_index]
    forms = await fetch_declensions(LangType.EN, WordType.ADJECTIVE, token.text, token)

    if forms is not None:
        if forms["is_absolute"]:
            return "no_change"

        target_form = find_matching_form(forms, token.text)
        if target_form is not None:
            return target_form

    # Fallback code
    text_lower = token.text.lower()
    if text_lower == token.lemma_:
        target_form = "no_change"
    else:
        adjective = Adjective(token.lemma_.lower())

        if adjective.is_singular() == text_lower:
            target_form = "singular"
        elif adjective.comparative() == text_lower:
            target_form = "comparative"
        elif adjective.superlative() == text_lower:
            target_form = "superlative"
        else:
            target_form = None

    if (
        target_form is None
        and settings.log_missing_declension
        and len(token.text) > 2
        and check_word_case(token.text, False)
    ):
        logger.error(
            f"English adjective target form could not be determined for '{token.text}' (lemma: '{token.lemma_}', idx: '{token.idx}')."
        )

    return target_form


async def find_form_noun_german(
    token_index: int, tokens: Doc, is_singular: bool|None = None
):
    token = tokens[token_index]

    if await check_word_type(LangType.DE, token, WordType.PRONOUN, True, True):
        return "no_change"

    return await find_form_noun_german_text(token.text, token, is_singular)


async def find_form_noun_german_text(text: str, token: Token, is_singular: bool):
    case = fetch_case(token)
    if case:
        flexion = case + " " + ("plural" if is_singular is False else "singular")
        return noun_form_map[flexion]

    stripped_text = remove_gender_ending(text)
    forms = await german_noun_lookup(stripped_text, token)
    if forms is None:
        if (
            settings.log_missing_declension
            and token.ent_type_ == ""
            and len(text) > 2
            and check_word_case(text, True)
            and not await check_word_type(
                LangType.DE, token, WordType.PRONOUN, True, True
            )
        ):
            logger.error(f"German noun declension not found for '{text}', idx: '{token.idx}'")

        return None

    target_form = find_matching_form(forms, stripped_text, is_singular)
    if (
        target_form is None
        and settings.log_missing_declension
        and check_word_case(text, True)
    ):
        logger.error(
            f"German noun target form could not be determined for '{text}' (lemma: '{token.lemma_}', idx: '{token.idx}')."
        )

    return target_form


async def find_form_noun_english(is_singular: bool):
    if is_singular:
        return "no_change"

    return "plural"


def check_word_case(text: str, is_first_upper: bool|None = None):
    if text.endswith("-"):
        return False

    words = text.split("-")
    for word in words:
        if len(word) == 0:
            continue

        if is_first_upper is not None:
            if word[0].isupper() != is_first_upper:
                return False

            word = word[1:]

        if not word.islower():
            return False

    return True


async def find_form(
    lang: LangType,
    word_type: WordType,
    token_index: int,
    tokens: Doc,
    is_singular: bool|None = None,
):
    if lang == LangType.FR:
        return tokens[token_index].text

    token = tokens[token_index]
    match word_type:
        case WordType.VERB:
            if lang == LangType.DE:
                return await find_form_verb_german(token_index, tokens)

            return await find_form_verb_english(token_index, tokens)
        case WordType.ADJECTIVE | WordType.ADVERB:
            if lang == LangType.DE:
                return await find_form_adjective_german(token_index, tokens)

            return await find_form_adjective_english(token_index, tokens)

        case WordType.NOUN | WordType.PRONOUN:
            if lang == LangType.DE:
                if token.text.endswith("-") and is_singular:
                    return "no_change"

                return await find_form_noun_german(token_index, tokens, is_singular)

            return await find_form_noun_english(is_singular)

    if (
        settings.log_missing_declension
        and len(word_type)
        and len(token.text) > 3
        and check_word_case(token.text)
    ):
        word_type = await fetch_word_type(lang, token)
        if word_type in ['n', 'v', 'a']:
            logger.error(
                f"Declension in '{lang}' not found for '{token.text}' (lemma: '{token.lemma_}', tag: '{token.tag_}, pos: '{token.pos_}', idx: '{token.idx}')"
            )

    return None


async def align_form_noun_german(
    target_form: str, target_token: Token, prefix: str | None = None
) -> str:
    # TODO determine correct form
    if target_token.text.islower() or await check_word_type(
        LangType.DE, target_token, WordType.PRONOUN, True, True
    ):
        return target_token.text

    target_result = await german_noun_lookup(target_token.text, target_token, prefix)

    text = get_target_declension_form(target_result, target_form)
    if text is None:
        if settings.log_missing_declension and check_word_case(target_token.text, True):
            logger.error(
                f"German noun target form '{str(target_form)}' for '{target_token.text}' (lemma: '{target_token.lemma_}') missing: '{json.dumps(target_result)}'."
            )

        return target_token.text

    return text


async def align_form_noun_english(target_form: str, target_token: Token) -> str:
    if target_token.text == "they":
        return target_token.text

    target_result = await fetch_declensions(
        LangType.EN, WordType.NOUN, target_token.text, target_token
    )

    text = get_target_declension_form(target_result, target_form)
    if text is None:
        if settings.log_missing_declension and check_word_case(target_token.text):
            logger.error(
                f"English noun plural for '{target_token.text}' (lemma: '{target_token.lemma_}') missing: '{json.dumps(target_result)}'."
            )

        return Noun(target_token.text).plural()

    return text


async def align_form_noun(
    lang: LangType, target_form: str, target_token: Token, prefix: str | None = None
) -> str:
    if target_form == "no_change" or target_form is None or lang == LangType.FR:
        return target_token.text

    if lang == LangType.DE:
        return await align_form_noun_german(target_form, target_token, prefix)

    return await align_form_noun_english(target_form, target_token)


def align_form_adjective_english(
    target_form: str | None,
    source_text: str,
    source_lemma: str,
    target_token: Token,
    target_result: dict | None,
) -> str:
    # use a_token.text to handle "consulting"
    source_text_lower = source_text.lower()

    if target_form is None:
        # Fallback code
        a_adjective_lemma = Adjective(source_lemma)
        if a_adjective_lemma.is_singular() == source_text_lower:
            target_form = "singular"
        elif a_adjective_lemma.comparative() == source_text_lower:
            target_form = "comparative"
        elif a_adjective_lemma.superlative() == source_text_lower:
            target_form = "superlative"
        else:
            target_form = None

    if target_form is None:
        if settings.log_missing_declension and len(source_text) > 2:
            logger.error(
                f"English adjective target form could not be determined for '{source_text}' (lemma: '{source_lemma}')."
            )

        return target_token.text

    if target_result is None:
        b_adjective = Adjective(target_token.lemma_)

        if target_form == "singular":
            text = b_adjective.singular()
        elif target_form == "comparative":
            text = b_adjective.comparative()
        elif target_form == "superlative":
            text = b_adjective.superlative()
        else:
            text = target_token.text

        if settings.log_missing_declension and check_word_case(
            target_token.text, False
        ):
            logger.error(
                f"English adjective data missing for '{target_token.text}' (lemma: '{target_token.lemma_}'), generated '{text}' for target form '{str(target_form)}'."
            )

        return text

    text = get_target_declension_form(target_result, target_form)
    if text is None:
        if settings.log_missing_declension and len(target_token.text) > 2:
            logger.error(
                f"English adjective target form '{str(target_form)}' for '{target_token.text}' (lemma: '{target_token.lemma_}') missing: {json.dumps(target_result)}"
            )

        return target_token.text

    return text


def align_form_adjective_german(
    target_form: str,
    target_token: Token,
    target_result: dict,
) -> str:
    text = target_token.text
    if target_result is not None and text != target_result["base_form"]:
        return text

    if target_form is None:
        ending = ""
    elif target_form in [
        "base_form",
        "comparative",
        "superlative",
    ]:
        text_aligned = get_target_declension_form(target_result, target_form)
        if text_aligned is not None:
            return text_aligned

        ending = ""
    else:
        ending = target_form

    if target_result is not None:
        if ending != "ste":
            if target_result["is_absolute"] == True:
                return text
        elif target_result is not None:
            text = target_result["superlative"].removesuffix("sten")

    if len(ending) and ending[0] != "e":
        if not ending.startswith("ste"):
            ending = ""
        elif text.endswith("t") or text.endswith("s"):
            ending = "e" + ending
    elif text[-1] == "e":
        ending = ending[1:]

    return text + ending


def align_form_adjective_french(
    target_form: str,
    target_token: Token,
) -> str:
    text = target_token.text

    if target_form == "performantes":
        if text.endswith("l") or text.endswith("é"):
            text += "e"

        text += "s"
    elif target_form == "ambitieuse":
        if text.endswith("é"):
            text += "e"

    return text


async def align_form_adjective(
    lang: LangType,
    target_form: str,
    source_text: str,
    source_lemma: str,
    target_token: Token,
) -> str:
    if target_form == "no_change" or target_form is None:
        return target_token.text

    if lang == LangType.FR:
        return align_form_adjective_french(target_form, target_token)

    target_result = await fetch_declensions(
        lang, WordType.ADJECTIVE, target_token.text, target_token
    )

    if lang == LangType.DE:
        return align_form_adjective_german(target_form, target_token, target_result)

    return align_form_adjective_english(
        target_form, source_text, source_lemma, target_token, target_result
    )


async def german_verb_splittable(word: str) -> str | None:  # pragma: no cover
    if settings.log_missing_declension and not word.isupper():
        logger.error(
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
        return None

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

    for prefix in static_rules[LangType.DE]["splittable_words"]:
        if word.startswith(prefix):
            if word in static_rules[LangType.DE]["splittable_words"][prefix]:
                return prefix

            return None

    # detect "adjective + verb" case
    letter_index = 2  # skip the first 2 letters
    while letter_index < len(word) - 2:  # skip the last 2 letters
        prefix = word[0:letter_index]
        partial_word = word[letter_index:]
        partial_word_result = await fetch_declensions(
            LangType.DE, WordType.VERB, partial_word
        )
        if partial_word_result is not None:
            tokens = fetch_tokens(LangType.DE, prefix + " " + partial_word)
            if WordType.ADJECTIVE == await fetch_word_type(
                LangType.DE, tokens[0]
            ) and WordType.VERB == await fetch_word_type(LangType.DE, tokens[1]):
                return prefix

        letter_index += 1

    return None


def find_matching_form(
    forms: dict | None, text: str, is_singular: bool | None = None
) -> str | None:
    if forms is None:
        return forms

    text_lower = text.lower()

    for form in forms:
        if is_singular is not None:
            if is_singular:
                if form.startswith("pl_"):
                    continue
            elif form.startswith("sg_"):
                continue

        if isinstance(forms[form], str) and forms[form].lower() == text_lower:
            return form.removesuffix("_2")

    return None


async def align_form_verb_german(
    target_form: str,
    source_text: str,
    source_lemma: str,
    target_token: Token,
    target_result: dict,
) -> str:
    text = get_target_declension_form(target_result, target_form)
    if text is not None:
        return text

    target_text = target_token.text

    # check if "zu" was stripped from the word in the lemma
    if source_text.count("zu") > source_lemma.count("zu"):
        prefix = await german_verb_splittable(target_text)
        if prefix:
            return prefix + "zu" + target_text[len(prefix) :]

        return "zu " + target_text

    # check if "ge" was stripped from the word in the lemma
    if source_text.count("ge") > source_lemma.count("ge"):
        prefix = await german_verb_splittable(target_text)
        if prefix:
            return prefix + "ge" + target_text[len(prefix) :]

        injected_string = "ge"
    else:
        injected_string = ""

    prefix = find_common_prefix(
        source_text,
        source_lemma,
    )

    ending = source_text[len(prefix) :]
    if injected_string and ending[0 : len(injected_string)] == injected_string:
        source_text = prefix + source_text[len(prefix) + len(injected_string) :]
        source_text = source_text.strip()
        prefix = find_common_prefix(source_text, source_lemma)
        ending = source_text[len(prefix) :]

    if (
        (source_lemma[-1] == "t" or source_lemma[-1] == "s")
        and len(ending)
        and ending[0] == "e"
    ):
        ending = ending[1:]

    # likely we did not find a useful ending (ie. 'gewinnen' for case 'gewannen' would give use 'annen')
    if len(ending) > 3:
        ending = ""
    else:
        remove = source_lemma[len(prefix) :]
        if remove:
            target_text = target_text[0 : -len(remove)]

        if ending != "" and len(target_text) > 2:
            if target_text.endswith("em"):
                ending = ""
            else:
                e_ending_letters = ["t", "n", "c", "v", "r", "h"]
                e_start_letters = ["t", "s", "n", "r"]
                if target_text[-1] in e_ending_letters and ending[0] in e_start_letters:
                    # einfachsten
                    if (
                        not target_text.endswith("en")
                        and not target_text.endswith("in")
                        and not target_text.endswith("ön")
                        and target_text[-1] != "h"
                        and ending[0:1] != "st"
                    ) or ending[0] == "n":
                        target_text += "e"
                elif target_text[-1] == "s":
                    target_text += "s"
                elif target_text[-1] == "e" and ending[0] == "e":
                    target_text = target_text[0:-1]

    if settings.log_missing_declension and not source_text.isupper():
        logger.error(
            f"German verb declension not found for '{source_text}' (lemma '{source_lemma}'): prefix '{prefix}', ending '{ending}' applies to '{target_token.text}' => {target_text}"
        )

    return target_text + ending


def align_form_verb_english(
    target_form: str | None, source_text: str, target_token: Token, target_result: dict | None
) -> str:
    if target_form is None:
        # Fallback code
        a_verb = Verb(source_text)
        if a_verb.is_singular():
            target_form = "third_person_singular"
        elif a_verb.is_past():
            target_form = "past_tense"
        elif a_verb.is_pres_part():
            target_form = "present_participle"
        elif a_verb.is_past_part():
            target_form = "past_participle"
        else:
            target_form = None

        if settings.log_missing_declension and not source_text.isupper():
            logger.error(
                f"English verb target form '{str(target_form)}' determined via fallback for '{source_text}'."
            )

    if target_form is None:
        return target_token.lemma_

    if target_result is None:
        b_verb = Verb(target_token.lemma_.lower())

        if target_form == "third_person_singular":
            text = b_verb.singular()
        elif target_form == "past_tense":
            text = b_verb.past()
        elif target_form == "present_participle":
            text = b_verb.pres_part()
        elif target_form == "past_participle":
            text = b_verb.past_part()
        else:
            text = target_token.lemma_

        if settings.log_missing_declension and not target_token.text.isupper():
            logger.error(
                f"English verb target form '{str(target_form)}' for '{target_token.text}' (lemma: '{target_token.lemma_}') generated '{text}'."
            )

        return text

    text = get_target_declension_form(target_result, target_form)
    if text is None:
        if settings.log_missing_declension and not target_token.text.isupper():
            logger.error(
                f"English verb target form '{str(target_form)}' for '{target_token.text}' (lemma: '{target_token.lemma_}') missing: '{json.dumps(target_result)}'."
            )

        return text

    return text


async def align_form_verb(
    lang: LangType,
    target_form: str,
    source_text: str,
    source_lemma: str,
    target_token: Token,
) -> str:
    if target_form == "no_change" or target_form is None or lang == LangType.FR:
        return target_token.text

    target_result = await fetch_declensions(
        lang, WordType.VERB, target_token.text, target_token
    )

    if lang == LangType.DE:
        return await align_form_verb_german(
            target_form, source_text, source_lemma, target_token, target_result
        )

    return align_form_verb_english(
        target_form, source_text, target_token, target_result
    )


def tokenize(text: str, lang: LangType) -> tuple:
    return tuple([i.text for i in model[lang].tokenizer(text)])


def alternative_a_english(
    alternative: str,
    prepend_word: bool,
    is_plural_alternative: bool,
) -> str:
    if alternative == "they":
        return alternative

    if (
        prepend_word
        and is_plural_alternative is False
        and not alternative.startswith(static_rules[LangType.EN]["a_not_startswith"])
        and not alternative.endswith(static_rules[LangType.EN]["uncountables"])
    ):
        alternative = (
            "an " + alternative
            if alternative[0].lower() in ["a", "e", "i", "o", "u"]
            else "a " + alternative
        )

    return alternative


async def alternative_declension(
    lang: LangType,
    target_form: str,
    source_text: str,
    source_lemma: str,
    word_type: str,
    prepend_word: bool,
    rule: Rule,
    alternative: Alternative,
    is_singular: bool,
    prefix: str | None = None,
) -> Alternative:
    if (
        alternative.is_remove
        or alternative.is_inspiration
        or len(alternative.lemma) == 0
        or "~" in alternative.lemma
    ):
        return alternative

    if len(alternative.words) > 5:
        return alternative

    word_count = len(rule.words)
    if prepend_word:
        word_count -= 1

    alternative_tokens = fetch_tokens(lang, alternative.lemma)
    if word_count > 1:
        # TODO figure out how to modify phrases
        new_alternative_lemma = alternative.lemma
        is_plural_alternative = is_token_plural(lang, alternative_tokens[-1])
    else:
        new_alternative_lemma = ""
        is_plural_alternative = False

        previous = False
        for alternative_index in reversed(range(len(alternative_tokens))):
            alternative_token = alternative_tokens[alternative_index]
            alternative_text = alternative_token.text
            if alternative_text != "," and token_is_conjunction(alternative_token):
                previous = False
            else:
                declension = (
                    not previous
                    and alternative.word_types[alternative_index]["lemmatize"]
                )
                if declension:
                    if alternative.word_types[alternative_index]["word_type"]:
                        alternative_word_type = alternative.word_types[
                            alternative_index
                        ]["word_type"]
                    elif len(alternative_tokens) == 1:
                        # in this case we just assume it is the same to avoid issues with word type detection
                        alternative_word_type = word_type
                    else:
                        alternative_word_type = await fetch_word_type(
                            lang, alternative_token, word_type, False
                        )

                    if WordType.VERB == word_type and (
                        (lang == LangType.EN and alternative_index == 0)
                        or WordType.VERB in alternative_word_type
                    ):
                        previous = True
                        alternative_text = await align_form_verb(
                            lang,
                            target_form,
                            source_text,
                            source_lemma,
                            alternative_token,
                        )
                    elif (
                        WordType.NOUN == word_type
                        and WordType.NOUN == alternative_word_type
                    ):
                        if is_token_plural(lang, alternative_token):
                            is_plural_alternative = True

                        previous = True
                        alternative_text = (
                            alternative_token.text
                            if alternative.is_collective_noun
                            or alternative.is_gendered_noun
                            else await align_form_noun(
                                lang,
                                target_form,
                                alternative_token,
                                prefix,
                            )
                        )
                    elif (
                        WordType.ADJECTIVE == word_type
                        and WordType.ADJECTIVE == alternative_word_type
                    ):
                        previous = True
                        alternative_text = await align_form_adjective(
                            lang,
                            target_form,
                            source_text,
                            source_lemma,
                            alternative_token,
                        )

            new_alternative_lemma = (
                alternative_text + alternative_token.whitespace_ + new_alternative_lemma
            )

    new_alternative = deepcopy(alternative)
    if lang == LangType.EN and prepend_word:
        new_alternative.lemma = alternative_a_english(
            new_alternative_lemma, prepend_word, is_plural_alternative
        )
    else:
        new_alternative.lemma = new_alternative_lemma
        if (
            is_singular != False
            and is_plural_alternative
            and new_alternative.is_collective_noun
        ):
            new_alternative.is_inspiration = True

    return new_alternative


async def alternatives_declension(
    lang: LangType,
    text: str,
    token_index: int,
    tokens: Doc,
    target_form: str,
    rule: Rule,
    alternatives: list[Alternative],
    is_singular: bool,
) -> tuple[str, int, list[Alternative]]:
    if (
        len(rule.words) > 1
        or rule.is_pattern_match
        or alternatives == None
        or len(alternatives) == 0
        or (len(alternatives) == 1 and alternatives[0].is_remove)
    ):
        return text, tokens[token_index].idx, alternatives

    word_types = rule.get_word_types()
    word_type = (
        word_types[0]
        if (len(word_types) == 1 and word_types[0] != "")
        else await fetch_word_type(lang, tokens[token_index])
    )

    prepend_word = False
    if (
        lang == LangType.EN
        and token_index > 0
        and (
            tokens[token_index - 1].text.lower() == "a"
            or tokens[token_index - 1].text.lower() == "an"
        )
    ):
        text = tokens[token_index - 1].text + " " + text
        start = tokens[token_index - 1].idx
        prepend_word = tokens[token_index - 1].text
    else:
        start = (
            tokens[token_index]._.start
            if tokens[token_index]._.start is not None
            else tokens[token_index].idx
        )
        if tokens[token_index]._.text is not None:
            text = tokens[token_index]._.text

    return (
        text,
        start,
        [
            await alternative_declension(
                lang,
                target_form,
                text,
                tokens[token_index].lemma_,
                word_type,
                prepend_word,
                rule,
                alternative,
                is_singular,
            )
            for alternative in alternatives
        ],
    )


def add_german_prefix(word: str, prefix: str) -> str:
    if len(prefix) == 0 or word.startswith(prefix):
        return word

    if not word.startswith("-") and not prefix.endswith("-"):
        word = word[0].lower() + word[1:]

    return prefix + word


def handle_single_tilde(alternative: Alternative, prefix: bool, is_singular: bool):
    lemma = ""
    word_types = []
    # ideally we use alternative.words here but we strip out the "~" in the rule editor
    words = alternative.lemma.split()
    for word_index in range(len(words)):
        word = words[word_index]
        if word.count("~") == 1:
            slash = False
            if word.startswith("~"):
                word = add_german_prefix(word[1:], prefix)
            else:
                position = word.find("~")
                if word[position+1].islower():
                    # Trans~gender => Trans*gender, qualifiziert~e => qualifiziert*e, ihr~e => ihr*e
                    if position + 3 < len(word) or is_singular:
                        word = word.replace("~", "/")
                        slash = True
                    # ihr~e => ihre
                    elif word.endswith("e"):
                        word = word.replace("~", "")
                    # qualifizierte~r => qualifizierte
                    else:
                        word = word[0:position]

                    if slash:
                        word_types.append(alternative.word_types[word_index])
                        word_types.append(
                            {"word_type": "", "lower_case": True, "lemmatize": True}
                        )

        word_types.append(alternative.word_types[word_index])
        lemma += " " + word

    alternative.word_types = word_types
    alternative.lemma = lemma.strip()


async def noun_alternatives(lang: LangType, separator: str, noun_separator: str, male_form: str, female_form: str) -> dict[str]:
    sentence_male_tokens = fetch_tokens(lang, male_form)
    sentence_female_tokens = fetch_tokens(lang, female_form)
    if len(sentence_male_tokens) != len(sentence_female_tokens):
        return {}

    singular_conjunction = "/" if lang == LangType.DE else " ou "
    plural_conjunction = " und " if lang == LangType.DE else " et "

    inclusive_form = ""
    binary_form = ""
    male_form_sub_sentence = ""
    female_form_sub_sentence = ""
    sub_sentence_contains_noun = False

    for token_index in range(len(sentence_male_tokens)):
        if lang == LangType.FR:
            if token_index > 0 and sentence_male_tokens[token_index - 1].lemma_ in static_rules[lang]["masculine_articles"]:
                is_noun = True
                sub_sentence_contains_noun = True
            else:
                is_noun = await _fetch_word_type(lang, sentence_male_tokens[token_index], WordType.NOUN, True, True) == WordType.NOUN
                if sub_sentence_contains_noun == True or is_noun:
                    sub_sentence_contains_noun = True

        if sentence_male_tokens[token_index].text != sentence_female_tokens[token_index].text:
            inclusive_form+= inclusive_alternative(
                lang,
                sentence_male_tokens[token_index].text,
                sentence_female_tokens[token_index].text,
                "",
                separator,
                noun_separator,
            )
            conjunction = singular_conjunction if is_token_singular(lang, sentence_male_tokens[token_index]) else plural_conjunction
            if lang == LangType.FR:
                if male_form_sub_sentence != "":
                    male_form_sub_sentence+= sentence_male_tokens[token_index - 1].whitespace_
                    female_form_sub_sentence+= sentence_female_tokens[token_index - 1].whitespace_

                male_form_sub_sentence+= sentence_male_tokens[token_index].text
                female_form_sub_sentence+= sentence_female_tokens[token_index].text if token_index > 0 or is_noun else sentence_female_tokens[token_index].text.lower()
            else:
                binary_form+= sentence_female_tokens[token_index].text + conjunction + sentence_male_tokens[token_index].text
        else:
            inclusive_form+= sentence_male_tokens[token_index].text
            if male_form_sub_sentence != "":
                if sub_sentence_contains_noun:
                    binary_form+= male_form_sub_sentence + conjunction + female_form_sub_sentence + sentence_female_tokens[token_index - 1].whitespace_
                else:
                    # TODO add user preference to choose male form over female form
                    binary_form+= female_form_sub_sentence + sentence_male_tokens[token_index - 1].whitespace_
                male_form_sub_sentence = ""
                female_form_sub_sentence = ""
                sub_sentence_contains_noun = False

            binary_form+= sentence_male_tokens[token_index].text

        inclusive_form+= sentence_male_tokens[token_index].whitespace_

        if male_form_sub_sentence == "":
            binary_form+= sentence_male_tokens[token_index].whitespace_

    if male_form_sub_sentence != "":
        binary_form+= male_form_sub_sentence + conjunction + female_form_sub_sentence

    return {
        GenderedRolesFormatType.INCLUSIVE_GENDER: inclusive_form,
        GenderedRolesFormatType.BINARY_GENDER: binary_form,
    }


def inclusive_alternative(
    lang: LangType,
    male_form: str,
    female_form: str,
    prefix: str,
    separator: str,
    noun_separator: str,
):
    if lang == LangType.DE:
        if male_form.lower() in static_rules[lang]["masculine_articles"]:
            return female_form + separator + male_form

        short_gender_star = True
        common_prefix = (
            ""
            if male_form.endswith("mann")
            else find_common_prefix(male_form, female_form, False, False)
        )
        if len(male_form) - len(common_prefix) > 2:
            common_prefix = female_form
            suffix = add_german_prefix(male_form, prefix)
            short_gender_star = False
        elif len(female_form) >= len(male_form):
            # Mitarbeiterin + Mitarbeiter = Mitarbeiter
            suffix = female_form[len(common_prefix) :]
        else:
            # Vorgesetze + Vorgesetzter = Vorgesetze
            suffix = male_form[len(common_prefix) :]

        temp_separator = noun_separator
        # In
        if separator != noun_separator:
            if short_gender_star:
                suffix = upperfirst(suffix)
            else:
                temp_separator = "/"

        return add_german_prefix(common_prefix + temp_separator + suffix, prefix)

    if lang == LangType.FR:
        male_form_lower = male_form.lower()
        if male_form_lower in static_rules[lang]["masculine_articles"]:
            inclusive_form = static_rules[lang]["masculine_articles"][male_form_lower]
            if male_form != male_form_lower:
                inclusive_form = upperfirst(inclusive_form)
            return inclusive_form

        common_prefix = find_common_prefix(male_form, female_form, False, False)
        if len(common_prefix) < 3:
            return male_form + separator + female_form.lower()

        if len(female_form) >= len(male_form):
            suffix = female_form[len(common_prefix) :]
            common_prefix = male_form
        else:
            suffix = male_form[len(common_prefix) :]
            common_prefix = female_form

        common_prefix = common_prefix[0:-1] if common_prefix[-1] == suffix[-1] else common_prefix

        return prefix + common_prefix + separator + suffix


async def gendered_alternatives(
    alternative: str,
    inclusive: bool,
    binary: bool,
    separator: str,
    noun_separator: str,
    additional_words: list = [],
    is_singular: bool = True,
    target_form: str = "base_form",
    token_index: int | None = None,
    tokens: Doc | None = None,
    full_text: str | None = None,
    prefix: str = "",
    binary_case: bool = False,
):
    alternatives = {}
    alternative_prefix = alternative_suffix = ""
    male_forms = None

    token_debug = "" if token_index is None else f", idx: '{tokens[token_index].idx}'"

    words = alternative.split(" ")
    for word in words:
        if not word.startswith("~") and "~" in word:
            male_form, female_form = word.split("~")
            male_forms = await german_noun_lookup(male_form, None, prefix)
            if male_forms is None or target_form not in male_forms:
                male_forms = None
                logger.error(f"Declension '{target_form}' missing for '{word}'{token_debug}")
                break

            if female_form is None:
                logger.error(f"Declension data missing for other form in '{word}'{token_debug}")
                return [], False

            female_forms = await german_noun_lookup(female_form, None, prefix)
            if female_forms is None or target_form not in female_forms:
                male_forms = True
                logger.error(f"Declension '{target_form}' missing for '{female_form}'{token_debug}")
                return [], False

        elif male_forms is None:
            alternative_prefix += word + " "
        else:
            alternative_suffix += " " + word

    if male_forms is None:
        logger.error(f"Missing male_form '{word}' in '{alternative}'{token_debug}")
        return [], binary_case

    female_form = female_forms[target_form]
    male_form = male_forms[target_form]

    if male_form == female_form:
        alternative = alternative_prefix + male_form + alternative_suffix
        alternatives[alternative] = False
        return alternatives, binary_case

    if female_form is not None and male_form is not None:
        if inclusive:
            lemma = inclusive_alternative(
                LangType.DE,
                male_form,
                female_form,
                prefix,
                separator,
                noun_separator,
            )

            if is_false_positive(
                full_text,
                token_index,
                tokens,
                [lemma],
                len(lemma),
            ):
                return None, binary_case

            additional_prefix = ""
            for additional_word in additional_words:
                additional_prefix += (
                    inclusive_alternative(
                        LangType.DE,
                        additional_word["male_form"],
                        additional_word["female_form"],
                        "",
                        separator,
                        noun_separator,
                    )
                    + "-"
                )

            alternatives[
                alternative_prefix.replace("/", separator)
                + additional_prefix
                + lemma
                + alternative_suffix.replace("/", separator)
            ] = False

        female_form = add_german_prefix(female_form, prefix)
        male_form_without_prefix = male_form
        male_form = add_german_prefix(male_form, prefix)

        separator = "/" if is_singular else " und "
        lemma = female_form + separator + male_form
        false_positive_check = [
            lemma,
            male_form + separator + female_form,
        ]

        if not is_singular:
            # Arbeitskolleginnen und -kollegen
            false_positive_check.append(
                female_form + separator + "-" + male_form_without_prefix.lower()
            )

        # case text = Mitarbeiterinnen: Mitarbeiterinnen und Mitarbeiter
        if is_false_positive(
            full_text,
            token_index,
            tokens,
            false_positive_check,
            0,
            len(lemma),
        ):
            # Suggest gender inclusive
            if binary and tokens[token_index].text == female_form:
                return None, binary_case

            binary_case = True

        form_max = max(len(female_form), len(male_form))

        # case text = Mitarbeiter: Mitarbeiterinnen und Mitarbeiter
        if is_false_positive(
            full_text,
            token_index,
            tokens,
            false_positive_check,
            form_max + len(separator),
            form_max,
        ):
            return None, binary_case

        if binary:
            additional_prefix = ""
            for additional_word in additional_words:
                additional_prefix += (
                    additional_word["female_form"]
                    + "/"
                    + additional_word["male_form"]
                    + "-"
                )

            new_alternative = (
                alternative_prefix + additional_prefix + lemma + alternative_suffix
            )
            alternatives[new_alternative] = False

        additional_prefix = ""
        for additional_word in additional_words:
            if additional_word["collective_noun"] is not None:
                additional_prefix += additional_word["collective_noun"] + "-"

    for form in ["collective_noun", "collective_noun_2"]:
        if male_forms[form] is not None:
            new_alternative = (
                alternative_prefix
                + additional_prefix
                + add_german_prefix(male_forms[form], prefix)
                + alternative_suffix
            )
            alternatives[new_alternative] = True

    return alternatives, binary_case


def get_german_noun_separator(german_gender_ending: GermanGenderEndingType):
    if german_gender_ending == GermanGenderEndingType.CAPITAL_LETTER:
        separator = "/"
        noun_separator = ""
    else:
        separator = noun_separator = german_gender_ending[0:-2]

    return separator, noun_separator


async def gendered_nouns(
    config: Config,
    lang: Language,
    text: str,
    tokens: Doc,
    token_index: int,
    alternatives: list[Alternative],
    subcategory: str,
    is_singular: bool | None,
    rule: Rule,
    full_text: str,
    target_form: str,
) -> tuple[str | None, str | None, list[Alternative], None]:
    if (
        rule.type == RuleType.SUFFIX
        and not tokens[token_index].lemma_.endswith("frau")
        and not tokens[token_index].lemma_.endswith("mann")
        and tokens[token_index].lemma_.lower().endswith(rule.lemma.lower())
    ):
        lemma_lower = rule.lemma.lower().replace("ä", "a")
        # strip of last two chars to handle "Beauftragter" vs. "Beauftragten"
        if lemma_lower.endswith("er") or lemma_lower.endswith("e"):
            lemma_lower = lemma_lower[0:-2]

        prefix_end = text.lower().replace("ä", "a").find(lemma_lower)
        prefix = text[0:prefix_end]
    else:
        prefix = ""

    binary_case = False
    inclusive = gendered_roles_format_inclusive(config.gendered_roles_format)
    binary = gendered_roles_format_binary(config.gendered_roles_format)
    separator, noun_separator = get_german_noun_separator(config.german_gender_ending)
    additional_words = []
    is_singular = True if is_singular is None else is_singular
    if (
        target_form
        not in declensions_config[LangType.DE][BasicWordType.NOUN]["columns"]
    ):
        target_form = "sg_nom" if is_singular else "pl_nom"

    if prefix.endswith("-"):
        words = prefix[:-1].split("-")
        word_filter = ("?," * len(words)).removesuffix(",")

        query = f"SELECT base_form, male_form, female_form, collective_noun FROM rules_germannoun WHERE base_form IN ({word_filter})"
        rows = await fetch_rows(query, words.copy())

        male_noun_map = {}
        female_noun_map = {}
        for row in rows:
            if row[2] is not None:
                male_noun_map[row[0]] = {
                    "female_form": row[2],
                    "collective_noun": row[3],
                }
            elif row[1] is not None:
                female_noun_map[row[0]] = {
                    "male_form": row[1],
                    "collective_noun": row[3],
                }

        if len(male_noun_map) or len(female_noun_map):
            prefixes = []
            for word in words:
                if word in male_noun_map:
                    male_form = word
                    female_form = male_noun_map[word]["female_form"]
                    collective_noun = male_noun_map[word]["collective_noun"]
                elif word in female_noun_map:
                    female_form = word
                    male_form = female_noun_map[word]["male_form"]
                    collective_noun = female_noun_map[word]["collective_noun"]
                else:
                    prefixes.append(word)
                    continue

                prefix = ("-").join(prefixes) + "-" if len(prefixes) else ""
                additional_words.append(
                    {
                        "word": word,
                        "male_form": prefix + male_form,
                        "female_form": prefix + female_form,
                        "collective_noun": (
                            prefix + collective_noun
                            if collective_noun is not None
                            else None
                        ),
                    }
                )
                prefixes = []

            prefix = ("-").join(prefixes)

    target_form = (
        "base_form"
        if target_form is None or target_form == "no_change"
        else target_form
    )

    new_alternatives = []
    for alternative in alternatives:
        if alternative.is_remove or alternative.is_inspiration:
            new_alternatives.append(alternative)
            continue

        if "~" in alternative.lemma:
            handle_single_tilde(alternative, prefix, is_singular)

        if not alternative.is_gendered_noun:
            alternative = await alternative_declension(
                lang.lang,
                target_form,
                text,
                tokens[token_index].lemma_,
                WordType.NOUN,
                False,
                rule,
                alternative,
                is_singular,
                prefix if alternative.lemma.startswith(prefix) else None,
            )

            if inclusive and separator != "/":
                new_alternative = deepcopy(alternative)
                new_alternative.lemma = new_alternative.lemma.replace("/", separator)
                new_alternatives.append(new_alternative)

            new_alternatives.append(alternative)
            continue

        alternative_variations, binary_case = await gendered_alternatives(
            alternative.lemma,
            inclusive,
            binary,
            separator,
            noun_separator,
            additional_words,
            is_singular,
            target_form,
            token_index,
            tokens,
            full_text,
            prefix,
            binary_case,
        )

        # false positive
        if alternative_variations is None:
            return None, None, []

        if not is_sub_category_enabled(config, subcategory):
            continue

        for alternative_variation in alternative_variations:
            new_alternative = deepcopy(alternative)
            new_alternative.lemma = alternative_variation
            new_alternative.is_collective_noun = alternative_variations[
                alternative_variation
            ]
            new_alternative.is_gendered_noun = not alternative_variations[
                alternative_variation
            ]
            if is_singular != False and new_alternative.is_collective_noun:
                new_alternative.is_inspiration = True

            if (
                "/" in alternative_variation and "/-" not in alternative_variation
            ) or " und " in alternative_variation:
                for _ in range(text.count("-") + 1):
                    new_alternative.word_types.append(
                        {"word_type": "", "lower_case": True, "lemmatize": True}
                    )
                    new_alternative.word_types.append(
                        {"word_type": "n", "lower_case": True, "lemmatize": True}
                    )

            new_alternatives.append(new_alternative)

    if binary_case:
        if binary:
            subcategory = "gendered_denominations_ending_advanced"
        else:
            subcategory = (
                "function"
                if "mann" in text.lower()
                else "gendered_denominations_ending"
            )
            if rule.is_advanced:
                subcategory += "_advanced"

        if not is_sub_category_enabled(config, subcategory):
            return None, None, []

        text += (
            tokens[token_index].whitespace_
            + tokens[token_index + 1].text
            + tokens[token_index + 1].whitespace_
            + tokens[token_index + 2].text
        )
    elif subcategory == "function":
        forms = await german_noun_lookup(tokens[token_index].text)
        if forms is not None and forms["male_form"] is not None:
            subcategory = "gender_identity"
            rule.text_id = forms["base_form"]

    return text, subcategory, new_alternatives


def fetch_article_for_flexion(
    flexion: str|None, gender: str, article_text: str
) -> tuple[str, str, str, str]:
    if flexion is None:
        return None, None, None, None

    form, _ = flexion.split()
    if (
        article_text not in static_rules[LangType.DE][gender + "_articles"]
        or form not in static_rules[LangType.DE][gender + "_articles"][article_text]
    ):
        return None, None, None, None

    article_forms = static_rules[LangType.DE][gender + "_articles"][article_text][form]
    return article_forms[1], article_forms[2], article_forms[3], article_forms[5]


def gendered_roles_format_inclusive(gendered_roles_format: GenderedRolesFormatType):
    return gendered_roles_format in [
        GenderedRolesFormatType.BOTH,
        GenderedRolesFormatType.INCLUSIVE_GENDER,
    ]


def gendered_roles_format_binary(gendered_roles_format: GenderedRolesFormatType):
    return gendered_roles_format in [
        GenderedRolesFormatType.BOTH,
        GenderedRolesFormatType.BINARY_GENDER,
    ]


async def fetch_alternatives_with_article(
    config: Config,
    lang: LangType,
    tokens: Doc,
    token_index: int,
    is_singular: bool,
    word_types: list,
    alternatives: list[Alternative],
) -> list[Alternative] | None:
    if alternatives is None:
        return []

    if (
        lang == LangType.EN
        or token_index == 0
        or len(word_types) != 1
        or word_types[0] != WordType.NOUN
    ):
        return None

    if lang == LangType.FR:
        article_text = tokens[token_index - 1].text.lower()
        if article_text == "les":
            alternatives_with_article = []
            for alternative in alternatives:
                if alternative.is_remove:
                    continue

                article_alternative = ""
                if " le " not in alternative.lemma:
                    article_alternative = (
                        "l'" if alternative.lemma.startswith("é") else "les"
                    )

                if article_alternative != "":
                    if not article_alternative.endswith("'"):
                        article_alternative += tokens[token_index - 1].whitespace_
                    alternative.lemma = article_alternative + alternative.lemma

                alternatives_with_article.append(alternative)

            return alternatives_with_article

        return None

    if lang == LangType.DE and not is_singular:
        return None

    token = tokens[token_index]
    text = token.text
    gender = await german_noun_gender_lookup(text)
    if gender is None:
        return None

    article_text = tokens[token_index - 1].text.lower()

    (
        match_masculine,
        match_feminine,
        match_neuter,
        match_alternative,
    ) = fetch_article_for_flexion(fetch_flexion(token), gender, article_text)

    if match_alternative is None:
        return None

    separator, _ = get_german_noun_separator(config.german_gender_ending)

    alternatives_with_article = []
    for alternative in alternatives:
        if alternative.is_remove:
            alternatives_with_article.append(alternative)
            continue

        if alternative.is_gendered_noun:
            article_alternative = (
                match_alternative if match_alternative else article_text
            )
            if alternative.is_collective_noun or separator in alternative.lemma:
                # Mitarbeiter*in, Mitarbeitende
                article_alternative = article_alternative.replace("~", separator)
            else:
                # Mitarbeiterin/Mitarbeiter
                article_alternative = article_alternative.replace("~", "/")
        else:
            alternative_tokens = fetch_tokens(LangType.DE, alternative.words[-1])
            if is_token_plural(LangType.DE, alternative_tokens[0]):
                article_alternative = match_feminine
            else:
                gender = await german_noun_gender_lookup(alternative.words[-1])
                if gender is None:
                    article_alternative = tokens[token_index - 1].text
                else:
                    match gender:
                        case "masculine":
                            article_alternative = match_masculine
                        case "neuter":
                            article_alternative = match_neuter
                        case "feminine":
                            article_alternative = match_feminine
                        case _:
                            if alternative.lemma.endswith("in"):
                                article_alternative = match_feminine

        if article_alternative != "":
            article_alternative += tokens[token_index - 1].whitespace_
            alternative.lemma = article_alternative + alternative.lemma

        alternatives_with_article.append(alternative)

    return alternatives_with_article


async def regex_match(
    config: Config,
    client: Client,
    lang: LangType,
    full_text: str,
    token_index: int,
    tokens: Doc,
    offsets: dict,
    list_full: list,
    rules: list[Rule],
    check_case=None,
) -> list:
    token = tokens[token_index]

    for rule in rules:
        subcategory = is_sub_category_enabled(config, rule.subcategories)
        if not subcategory:
            continue

        connector_string = rule.word_types[-1]
        start = token.idx

        # run regex on exactly the token
        if rule.word_types[0] is None:
            text = check_text = token.text
            if connector_string not in token.text:
                continue

            start_token = token_index
        else:
            try:
                text = check_text = ""
                start_token = rule.word_types[0] + token_index
                max_end_token = rule.word_types[1] + token_index

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
                    if start_token >= token_index:
                        text += offset_token.text

                    if offset_token.whitespace_ != "":
                        break

                    start_token += 1
                    if tokens[start_token].text != connector_string:
                        break

                    check_text += connector_string
                    if start_token >= token_index:
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
            check_text = upperfirst(check_text.lower())
            if await german_noun_lookup(check_text) is None:
                continue

        # handle "Kund(-innen)"
        if text == ")" and "(" in check_text:
            ending_start = check_text.find("(")
            text = check_text[ending_start:]
            start = tokens[token_index - 1].idx + ending_start

        alternatives = rule.alternatives
        explanation = rule.explanation
        url = rule.url
        icon = rule.icon

        if subcategory == "d_and_i":
            if check_case == "gender_denom" and check_text.islower():
                text_split = text.split(connector_string)
                if (
                    text_split[0] not in static_rules[LangType.DE]["feminine_articles"]
                    or text_split[1]
                    not in static_rules[LangType.DE]["masculine_articles"]
                ):
                    continue

        elif subcategory == "gendered_denominations_ending_advanced":
            if check_text.islower():
                if connector_string == "/" and tokens[token_index - 1].text.islower():
                    text = tokens[token_index - 1].text + text

                text_split = text.split(connector_string)
                if (
                    text_split[0] not in static_rules[LangType.DE]["feminine_articles"]
                    or text_split[1]
                    not in static_rules[LangType.DE]["masculine_articles"]
                ):
                    continue

                alternatives = [
                    Alternative(
                        text.replace(connector_string, config.german_gender_ending[0])
                    )
                ]
            # Kundinnen -> Kund*innen
            elif text.lower().endswith("innen") or text.lower().endswith("innen)"):
                alternatives = [Alternative(alternatives[0].lemma + "nen")]
        elif subcategory.startswith("gender_specific_abbreviation"):
            has_advanced = is_sub_category_enabled(
                config, "gender_specific_abbreviation_advanced"
            )

            parenthesis = (
                token_index > 0
                and tokens[token_index - 1].text == "("
                and len(tokens) > token_index + len(text)
                and tokens[token_index + len(text)].text == ")"
            )

            letters = text
            if parenthesis:
                letters = letters[1:-1]

            letters = text.split("/")

            letters = list(map(lambda x: x.upper(), letters))
            is_lower = text[0].islower()

            all_letters = deepcopy(letters)

            veteran_letter = "V"
            diverse_letter = "D"
            if diverse_letter not in letters and "*" not in letters:
                letters.append(diverse_letter)
            elif not has_advanced:
                continue

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
                for letter_index in range(len(letters)):
                    if letters[letter_index] == "W":
                        letters[letter_index] = "F"
                        break

            if has_advanced:
                letters = sorted(letters)

            alternative = "/".join(letters)
            if is_lower:
                alternative = alternative.lower()
                diverse_letter = diverse_letter.lower()
                veteran_letter = veteran_letter.lower()
                x_letter = x_letter.lower()

            if parenthesis:
                start -= 1
                text = f"({text})"
                alternative = f"({alternative})"

            context_v = "include veterans"
            match lang.lang:
                case LangType.DE:
                    context_d = "Divers (EU) / m. Behinderung (NA)"
                    context_remove = "Nutze geschlechtsneutrale Job-Titel"
                    explanation = "Nenne unterrepräsentierte Gruppen zuerst. Verlinke auf deine Leitlinie zur Gleichstellung."

                    alternative = alternative.replace("f", "w")
                case LangType.EN:
                    context_d = "disabled (NA) / diverse (EU)"
                    context_remove = "Use gender neutral job title"
                    explanation = "Put underrepresented groups first and link to your equal opportunity policy"

            alternative_3 = None
            alternative = Alternative(alternative)
            if "*" in alternative.lemma:
                alternative_2 = alternative.lemma.replace("*", diverse_letter)
                alternative_v = alternative_2
                alternative_2 = Alternative(alternative_2)
                alternative_2.label = context_d
                if not without_x:
                    alternative_3 = alternative.lemma.replace("*", x_letter)
                    alternative_3 = Alternative(alternative_3)
            else:
                alternative_2 = alternative.lemma.replace(diverse_letter, "*")
                alternative_2 = Alternative(alternative_2)
                alternative_v = alternative.lemma
                if not without_x:
                    alternative_3 = alternative.lemma.replace(diverse_letter, x_letter)
                    alternative_3 = Alternative(alternative_3)

                alternative.label = context_d

            if lang.lang == LangType.EN:
                alternative_v = alternative_v.replace(
                    diverse_letter, diverse_letter + "/" + veteran_letter
                )
                alternative_v = Alternative(alternative_v)

                if without_v is False:
                    alternative_v.label = context_d
                    alternative = alternative_v
                else:
                    alternative_v.label = context_v

            remove_alternative = Alternative("-")
            remove_alternative.is_remove = True
            remove_alternative.label = context_remove
            alternatives = [
                remove_alternative,
                Alternative(
                    "Alle Gender" if lang.lang == LangType.DE else "all gender"
                ),
            ]

            # case "d/f/m/v" => do not suggest "d/v/f/m"
            if (
                len(all_letters) < len(alternative.lemma.split("/"))
                or (all_letters[0] != "d" and all_letters[0] != "*")
                or all_letters[-1] != "m"
            ):
                alternatives.append(alternative)

            if not has_advanced:
                alternative_sorted = Alternative("/".join(sorted(letters)))
                alternative_sorted.label = context_d

                if parenthesis:
                    alternative_sorted.lemma = f"({alternative_sorted.lemma})"

                if is_lower:
                    alternative_sorted.lemma = alternative_sorted.lemma.lower()

                alternatives.append(alternative_sorted)

            if lang.lang == LangType.EN and without_v:
                alternatives.append(alternative_v)

            if lang.lang == LangType.DE or "*" in alternative.lemma:
                alternatives.append(alternative_2)

            if alternative_3 is not None:
                alternatives.append(alternative_3)

        skip_token = start_token + 1

        list_full.append(
            ResultOut.factory(
                config,
                client,
                lang,
                text,
                rule.text_id,
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

    return token_index


async def is_rule_false_positive(
    full_text: str, token_index: int, tokens: Doc, rule: Rule
) -> bool:
    false_positives = await fetch_false_positives(rule)
    result = is_false_positive(full_text, token_index, tokens, false_positives)
    if result is False and rule.case_sensitive_false_positives is not None:
        result = is_false_positive(
            full_text,
            token_index,
            tokens,
            rule.case_sensitive_false_positives,
            None,
            None,
            True
        )

    return result


def is_false_positive(
    full_text: str | None,
    token_index: int | None,
    tokens: Doc | None,
    false_positives: list,
    window_left: int | None = None,
    window_right: int | None = None,
    case_sensitive: bool = False,
) -> bool:
    if len(false_positives) == 0 or full_text is None:
        return False

    if window_left is None:
        # previous 5 tokens
        i_window_min = max(0, token_index - 5)
        window_left = tokens[i_window_min].idx
    else:
        window_left = max(tokens[token_index].idx - window_left, 0)

    if window_right is None:
        # following 5 tokens
        i_window_max = min(len(tokens) - 1, token_index + 5)
        window_right = tokens[i_window_max].idx + len(tokens[i_window_max].text)
    else:
        window_right += tokens[token_index].idx

    partial_text = full_text[window_left:window_right]
    if not case_sensitive:
        partial_text = partial_text.lower()
        false_positives = list(map(lambda false_positive: false_positive.lower(), false_positives))

    start = tokens[token_index].idx - window_left
    end = start + len(tokens[token_index].text)

    for false_positive in false_positives:
        for m in re.finditer(re.escape(false_positive), partial_text):
            if m.start() <= start and m.end() >= end:
                return True

    return False


def map_rule_label_type(lang: LangType, label_type: str) -> str | None:
    if lang not in label_types or label_type not in label_types[lang]:
        return None

    return label_types[lang][label_type]


def fetch_sent_noun_chunks(sent: Span) -> list[Span]:
    chunks = []
    for chunk in sent.noun_chunks:
        chunks.append(chunk)

    return chunks


async def check_person_noun(
    rule: Rule,
    lang: LangType,
    tokens: Doc,
    chunks: list[str],
    token_chunk: Span
):
    skip = True
    noun_count = 0
    chunk_token_index = token_chunk.end
    while chunk_token_index >= token_chunk.start:
        chunk_token_index -= 1

        chunk_token = tokens[chunk_token_index]
        chunk_word_type = await fetch_word_type(
            lang,
            chunk_token,
        )

        # ignore noun's that match the rule (ie. "The project has become a *vegetable*, showing no signs of progress.")
        if (
            chunk_word_type == WordType.NOUN
            and (
                tokens[chunk_token_index].lemma_ == rule.lemma
                or tokens[chunk_token_index].text == rule.lemma
            )
        ):
            continue

        chunk_token_lemma_lower = chunk_token.lemma_.lower()
        if chunk_word_type == WordType.NOUN and chunk_token_lemma_lower in misc_words[lang.lang]:
            continue

        if chunk_word_type == WordType.NOUN or chunk_word_type == WordType.PRONOUN:
            noun_count += 1
            skip = chunk_word_type != WordType.PRONOUN and chunk_token_lemma_lower not in person_words[lang.lang]
            break

    # *He* is *a vegetable*
    if noun_count == 0 and token_chunk != chunks[0]:
        return await check_person_noun(rule, lang, tokens, chunks, chunks[0])

    return skip

async def rule_check(
    config: Config,
    client: Client,
    lang: Language,
    full_text: str,
    token_index: int,
    tokens: Doc,
    offsets: dict,
    list_full: list,
    rules: list[Rule],
    false_positive_matcher: list | None = None,
) -> list:
    token = tokens[token_index]
    if len(rules) == 0 or not is_valid_text(token.text):
        return token_index

    if token.lemma_ == "aber" and lang.lang == LangType.DE:
        preceeding_text = full_text[max(0, token.idx - 5) : token.idx]
        if (
            re.search(r"^ *$", preceeding_text) is not None
            or re.search(r"[.!?:,]\s*$", preceeding_text, re.MULTILINE) is not None
        ):
            return token_index

    for rule in rules:
        subcategory = is_sub_category_enabled(config, rule.subcategories)
        if not subcategory:
            continue

        if rule.entity_type != EntityType.DEFAULT:
            match rule.entity_type:
                case EntityType.NON_PERSON:
                    if (
                        token.ent_type_
                        and token.ent_type_
                        in static_rules["named_entity_labels"][EntityType.PERSON]
                    ):
                        continue
                case EntityType.PERSON:
                    if (
                        token.ent_type_
                        not in static_rules["named_entity_labels"][EntityType.PERSON]
                    ):
                        continue
                case EntityType.NON_NAME:
                    if (
                        token.ent_type_
                        and token.ent_type_
                        in static_rules["named_entity_labels"][EntityType.NAME]
                    ):
                        continue
                case EntityType.NAME:
                    if (
                        token.ent_type_
                        not in static_rules["named_entity_labels"][EntityType.NAME]
                    ):
                        continue

        if rule.type == RuleType.SUBSTRING:
            text = token.text
            token_lower = text.lower()
            rule_lemma_lower = rule.lemma.lower()
            count = token_lower.count(rule_lemma_lower)
            if count == 0:
                continue

            if rule.false_positives is not None:
                standard_words = (
                    rule.false_positives
                    + static_rules[LangType.DE]["standard_words"].copy()
                )

            for standard_word in standard_words:
                if standard_word.lower() not in rule_lemma_lower:
                    token_lower = token_lower.replace(standard_word.lower(), "")

            count = token_lower.count(rule_lemma_lower)
            if count == 0:
                continue

            skip_token = token_index + token._.token_index_offset
        else:
            skip_token, text = await is_phrase_match(
                lang.lang,
                token_index,
                tokens,
                rule,
                false_positive_matcher,
            )

            if not text or await is_rule_false_positive(
                full_text, token_index, tokens, rule
            ):
                continue

        is_singular = None
        for k in range(len(rule.words)):
            is_singular = is_token_singular(lang.lang, tokens[token_index + k])
            if is_singular is None:
                continue

            break

        if is_singular == True:
            if rule.pluralization == PluralizationType.PLURAL_ONLY:
                continue
        elif (
            is_singular == False
            and rule.pluralization == PluralizationType.SINGULAR_ONLY
        ):
            continue

        if rule.label_type == RuleLabelEnum.NOT_FOR_PEOPLE:
            token_chunk = None

            # TODO cache on the sentence?
            chunks = fetch_sent_noun_chunks(tokens[token_index].sent)
            for chunk in chunks:
                if chunk.start <= token_index < chunk.end:
                    token_chunk = chunk
                    break
                if chunk.start > token_index:
                    break

            if token_chunk is None:
                # No noun detected => assume false positive
                if len(chunks) == 0:
                    continue

                # If there is only one noun: ie. *You* are flexible / *Mitarbeiter* sind flexibel
                token_chunk = chunks[0]

                if len(chunks) > 1:
                    # Handle conjunctions
                    # Competition is our daily life *and* we love to be >challenged<.

                    sent_token_index = tokens[token_index].sent.start
                    while sent_token_index < tokens[token_index].sent.end:
                        if sent_token_index > token_index:
                            break

                        if token_is_conjunction(tokens[sent_token_index]):
                            for chunk in chunks:
                                if chunk.start < sent_token_index:
                                    token_chunk = chunk

                        sent_token_index += 1

            skip = await check_person_noun(rule, lang, tokens, chunks, token_chunk)

            # TODO cache on the token
            if skip:
                continue

        word_types = rule.get_word_types()

        alternatives = await fetch_rule_alternatives(
            client, rule, is_singular, config.show_inspiration_alternatives, lang.locale
        )

        if len(alternatives):
            form_token_i = token_index
            if rule.actual_word_types:
                word_type = rule.actual_word_types[0]
            else:
                expected_word_type = None
                if LangType.DE == lang.lang and len(word_types) > 1:
                    form_token_offset = 0
                    for k in range(len(word_types)):
                        if word_types[k] == WordType.NOUN:
                            expected_word_type = WordType.NOUN
                            form_token_offset = k

                    form_token_i += form_token_offset

                if expected_word_type is None:
                    expected_word_type = word_types[0] if len(word_types) else None

                word_type = await fetch_word_type(
                    lang.lang,
                    tokens[form_token_i],
                    expected_word_type,
                )
            target_form = await find_form(
                lang.lang, word_type, form_token_i, tokens, is_singular
            )

        gendered_noun = False
        if LangType.DE == lang.lang and len(alternatives):
            for alternative in alternatives:
                if alternative.lemma is not None and "~" in alternative.lemma:
                    gendered_noun = True
                    break

            if gendered_noun:
                (
                    text,
                    subcategory,
                    alternatives,
                ) = await gendered_nouns(
                    config,
                    lang,
                    text,
                    tokens,
                    token_index,
                    alternatives,
                    subcategory,
                    is_singular,
                    rule,
                    full_text,
                    target_form,
                )

            if text is None:
                continue

        if text.endswith("-"):
            ending = "s-" if text.endswith("s-") else "-"

            for alternative in alternatives:
                if (
                    alternative.lemma is not None
                    and alternative.lemma.endswith(ending) != ending
                ):
                    alternative.lemma += ending

        start = token.idx
        if lang.lang == LangType.FR:
            new_alternatives = []
            for alternative in alternatives:
                if alternative.is_gendered_noun:
                    male_form, female_form = alternative.lemma.split("~")
                    gendered_alternatives = await noun_alternatives(lang.lang, "·", "·", male_form, female_form)
                    for gendered_alternative in gendered_alternatives:
                        if config.gendered_roles_format == GenderedRolesFormatType.BOTH or config.gendered_roles_format == gendered_alternative:
                            new_alternative = deepcopy(alternative)
                            new_alternative.lemma = gendered_alternatives[gendered_alternative]
                            new_alternatives.append(new_alternative)
                else:
                    new_alternatives.append(alternative)

            alternatives = new_alternatives
        elif len(alternatives):
            # TODO make it possible to handle cases with multiple alternatives
            if len(alternatives) == 1 and alternatives[0].lemma == "they":
                text, alternative = await pluralize_they(text, tokens, token_index)
                alternatives = [Alternative(alternative)]
            elif not subcategory.startswith("abbreviation"):
                text, start, alternatives = await alternatives_declension(
                    lang.lang,
                    text,
                    token_index,
                    tokens,
                    target_form,
                    rule,
                    alternatives,
                    is_singular,
                )

                if subcategory.startswith("filler"):
                    text, alternatives = detect_filler_words_at_sentence_start(
                        alternatives,
                        text,
                        full_text,
                        start + len(text),
                    )

            alternatives_with_article = await fetch_alternatives_with_article(
                config,
                lang.lang,
                tokens,
                token_index,
                is_singular,
                word_types,
                alternatives,
            )

            if alternatives_with_article is not None:
                alternatives = alternatives_with_article
                start = tokens[token_index - 1].idx
                text = tokens[token_index - 1].text + " " + text

        label = token._.label if token._.label is not None else rule.label

        list_full.append(
            ResultOut.factory(
                config,
                client,
                lang,
                text,
                rule.text_id,
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
                label,
            )
        )

        if token._.child_token:
            list_full.append(
                ResultOut.factory(
                    config,
                    client,
                    lang,
                    token._.child_token.text,
                    token.lemma_,
                    full_text,
                    offsets,
                    subcategory,
                    token._.child_token.idx,
                    None,
                    alternatives,
                    None,
                    rule.explanation,
                    rule.url,
                    rule.icon,
                    label,
                )
            )

        return skip_token

    return token_index


def detect_filler_words_at_sentence_start(
    alternatives: list[Alternative], text: str, full_text: str, end: int
) -> tuple[str, list[Alternative]]:
    if alternatives == ["-"] and text[0].isupper():
        match = re.search(r"(\s*,\s*)(\S+)", full_text[end : end + 30])
        if isinstance(match, re.Match):
            text += match.group(0)
            alternatives = [upperfirst(match.group(2))]

    return text, alternatives


def token_is_conjunction(token: Token) -> bool:
    return token.text == "," or token.pos_ == "CCONJ"


async def pluralize_they(text: str, tokens: Doc, token_index: int) -> tuple[str, str]:
    token = tokens[token_index]
    alternative = "they"

    next_i = token_index + 1
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
            next_i == token_index + 1
            and tokens[next_i].text[-1] == "s"
            and WordType.VERB == await fetch_word_type(LangType.EN, tokens[next_i])
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


def get_emoji(emoji_text: str) -> str:
    return emoji.emojize(f":{emoji_text}:", language="alias")


def get_emoji_context(alternative: str, lang: LangType) -> str:
    return (
        emoji.demojize(alternative, language=lang)
        .replace(":", "")
        .replace("_", " ")
        .title()
    )


def detect_non_inclusive_emoji(
    config: Config,
    client: Client,
    lang: Language,
    full_text: str,
    token_index: int,
    tokens: Doc,
    offsets: dict,
    list_full: list,
) -> list:
    if (
        client.name == "web-ext"
        and client.version != "0.0.0"
        and client.version < VersionString("1.28.0.1")
    ):
        return token_index

    token = tokens[token_index]
    if not token._.is_emoji:
        return token_index

    token_count = len(tokens)

    # 👨🏽‍👩🏽‍👧🏽 case https://github.com/carpedm20/emoji/issues/204
    if (
        token_index + 1 < token_count
        and tokens[token_index + 1].text.endswith("\u200d")
    ) or (token_index > 0 and tokens[token_index - 1].text.endswith("\u200d")):
        return token_index

    alternatives = []
    explanation_context = get_emoji_context(token.text, lang.lang)

    emoji_description = token._.emoji_desc
    emoji_base = re.sub(r"\b[-a-z]+\b skin tone", "", emoji_description)

    emoji_base = emoji_base.strip().replace(" ", "_")

    subcategory = None
    for emoji_config_name in static_rules["emoji"]:
        emoji_config = static_rules["emoji"][emoji_config_name]
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
                static_rules["skin_tones"]["full"]
                if len(emojis) == 1
                else static_rules["skin_tones"]["minimal"]
            )
        else:
            skin_tones = []

        for alternative_text in emojis:
            if alternative_text == "-":
                alternative = Alternative("-")
                alternative.is_remove = True
                alternatives.append(alternative)

                continue

            alternative_text = emoji_base.replace(rule, alternative_text)
            alternative = get_emoji(alternative_text)

            # if person is not available, then check of "woman" is available
            if ":" in alternative and emoji_config_name == "person_gender":
                alternative_text = emoji_base.replace(rule, "woman")
                alternative = get_emoji(alternative_text)

            if ":" not in alternative and alternative != token.text:
                alternative = Alternative(alternative)
                alternative.label = get_emoji_context(alternative.lemma, lang.lang)
                alternatives.append(alternative)

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
                    alternative = Alternative(alternative)
                    alternative.label = get_emoji_context(alternative.lemma, lang.lang)
                    alternatives.append(alternative)

        if len(alternatives) == 1:
            continue

        # match found
        break

    if len(alternatives) == 0 and "skin tone" in emoji_description:
        subcategory = "culture"
        for skin_tone in static_rules["skin_tones"]["all"]:
            alternative = get_emoji(emoji_base + skin_tone)
            if ":" not in alternative and alternative != token.text:
                alternative = Alternative(alternative)
                alternative.label = get_emoji_context(alternative.lemma, lang.lang)
                alternatives.append(alternative)

    if "skin tone" in emoji_description:
        explanation = (
            "Be mindful when using a skin tone that does not match your own"
            if lang.lang == LangType.EN
            else "Vorsicht beim Verwenden von Hauttönen, die nicht den eigenen entsprechen"
        )
    else:
        explanation = None

    if subcategory and len(alternatives) >= 1:
        list_full.append(
            ResultOut.factory(
                config,
                client,
                lang,
                token.text,
                token.text,
                full_text,
                offsets,
                subcategory,
                token.idx,
                None,
                alternatives,
                None,
                explanation,
                None,
                None,
                explanation_context,
            )
        )

        return token_index + 1

    if token_index + 1 < len(tokens):
        subcategory = explanation = None
        emoji_index = token_index
        while emoji_index + 1 < len(tokens) and (tokens[emoji_index + 1]._.is_emoji or tokens[emoji_index+1].text.endswith("\u200d")):
            emoji_index += 1

            if token.text == tokens[emoji_index].text:
                subcategory = "ability"
                explanation = (
                    "Wiederholen von Emoji kann blinde Menschen ausschließen"
                    if lang.lang == LangType.DE
                    else "Repeating emoji's may exclude screen reader users"
                )
            elif explanation is not None:
                emoji_index -= 1
                break

        if subcategory is None and emoji_index >= token_index + 1:
            subcategory = "ability" if emoji_index >= token_index + 2 else "ability_advanced"

            explanation = (
                "Übermäßiger Gebrauch von Emoji kann blinde Menschen ausschließen"
                if lang.lang == LangType.DE
                else "Emoji overuse may exclude screen reader users"
            )

        if subcategory is not None and is_sub_category_enabled(config, subcategory):
            text = token.text
            for text_index in range(token_index, emoji_index):
                text += tokens[text_index].whitespace_ + tokens[text_index + 1].text

            alternatives = [Alternative(token.text), Alternative("-", None, None, True)]

            list_full.append(
                ResultOut.factory(
                    config,
                    client,
                    lang,
                    text,
                    text,
                    full_text,
                    offsets,
                    subcategory,
                    token.idx,
                    None,
                    alternatives,
                    None,
                    explanation,
                )
            )

            return emoji_index + 1

    return token_index


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
        log_level=settings.logger_config_level,
        server_header=False,
    )
