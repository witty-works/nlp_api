"""
LanguageTool-compatible API

Implements the LanguageTool HTTP API v2 protocol
(https://languagetool.org/http-api/) on top of the Witty check pipeline, so
any LanguageTool client with a custom-server setting (desktop app, browser
add-on, editor plugins) can be pointed at this service.

The endpoints live under the /lt prefix ("virtual directory") to keep them
apart from the versioned native API (/v2.4/check): clients configured with
`https://<host>/lt` as their server URL request `/lt/v2/check` and
`/lt/v2/languages`. With LANGUAGETOOL_COMPAT_ROOT enabled they are also
mounted at the root (/v2/check, ...), the exact layout of a real LanguageTool
server, for clients that build the URL themselves and cannot be given a path
— the desktop app pointed at localhost only accepts host and port.
"""

import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from app.auth_service import fetch_user
from app.config_manager import fetch_configs_for_request
from app.context import AppContext
from app.dependencies import get_app_context
from app.helper import utf16_offsets
from app.language_processor import apply_language_rules, fetch_text
from app.models import (
    CheckRequestIn,
    Client,
    Config,
    LangVariantType,
    LangWithAutoType,
    Result,
    ResultOut,
)

router = APIRouter(prefix="/v2")

LOCALE_NAMES = {
    "en-US": "English (US)",
    "en-GB": "English (GB)",
    "de-DE": "German (Germany)",
    "de-AT": "German (Austria)",
    "de-CH": "German (Swiss)",
    "fr-FR": "French",
}

SENTENCE_BOUNDARIES = ".!?\n"

# How much text to include on each side of a match in `context`, in
# characters. Matches the LanguageTool server's CONTEXT_SIZE.
CONTEXT_RADIUS = 40


class LTSoftware(BaseModel):
    name: str
    version: str
    buildDate: str
    apiVersion: int
    premium: bool
    status: str


class LTWarnings(BaseModel):
    incompleteResults: bool


class LTDetectedLanguage(BaseModel):
    name: str
    code: str
    confidence: float


class LTLanguage(BaseModel):
    name: str
    code: str
    detectedLanguage: LTDetectedLanguage


class LTReplacement(BaseModel):
    value: str


class LTContext(BaseModel):
    text: str
    offset: int
    length: int


class LTUrl(BaseModel):
    value: str


class LTCategory(BaseModel):
    id: str
    name: str


class LTRule(BaseModel):
    id: str
    description: str
    issueType: str
    category: LTCategory
    urls: list[LTUrl] | None = None


class LTMatchType(BaseModel):
    typeName: str


class LTMatch(BaseModel):
    message: str
    shortMessage: str
    offset: int
    length: int
    replacements: list[LTReplacement]
    context: LTContext
    sentence: str
    type: LTMatchType
    rule: LTRule
    ignoreForIncompleteSentence: bool = False
    contextForSureMatch: int = 0


class LTDetectedLanguageRate(BaseModel):
    language: str
    rate: float


class LTExtendedSentenceRange(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: int = Field(alias="from")
    to: int
    detectedLanguages: list[LTDetectedLanguageRate]


class LTCheckResponse(BaseModel):
    software: LTSoftware
    warnings: LTWarnings
    language: LTLanguage
    matches: list[LTMatch]
    sentenceRanges: list[list[int]] = []
    extendedSentenceRanges: list[LTExtendedSentenceRange] = []


class LTLanguageItem(BaseModel):
    name: str
    code: str
    longCode: str


def resolve_lang(language: str) -> LangWithAutoType | None:
    """Map a LanguageTool language code onto a supported locale or lang.

    Accepts long codes ("de-DE"), bare codes ("de"), "auto", and codes with
    extra subtags ("de-DE-x-simple-language").
    """
    try:
        return LangWithAutoType(language)
    except ValueError:
        pass

    parts = language.split("-")
    if len(parts) >= 2:
        try:
            return LangWithAutoType("-".join(parts[0:2]))
        except ValueError:
            pass

    try:
        return LangWithAutoType(parts[0])
    except ValueError:
        return None


def text_from_data(data: str) -> tuple[str, list[tuple[int, int]]]:
    """Flatten a LanguageTool `data` JSON document into plain text.

    Markup runs are replaced by their `interpretAs` text padded with spaces
    to the length of the markup (or spaces only, if `interpretAs` is longer),
    so every offset in the flattened text equals the offset in the original
    data stream and match positions need no mapping back. Also returns the
    (start, end) spans the markup occupies; matches overlapping those spans
    are artifacts of the padding and must be discarded.

    Besides the documented `annotation` list, the desktop app sends a bare
    `{"text": ...}` document; that shape is passed through as-is.
    """
    document = json.loads(data)

    if "annotation" not in document and isinstance(document.get("text"), str):
        return document["text"], []

    annotations = document.get("annotation", [])

    parts = []
    markup_spans = []
    position = 0
    for annotation in annotations:
        if "text" in annotation:
            parts.append(annotation["text"])
            position += len(annotation["text"])
        elif "markup" in annotation:
            markup_len = len(annotation["markup"])
            interpret_as = annotation.get("interpretAs", "")
            if len(interpret_as) > markup_len:
                interpret_as = ""

            parts.append(interpret_as + " " * (markup_len - len(interpret_as)))
            markup_spans.append((position, position + markup_len))
            position += markup_len

    return "".join(parts), markup_spans


def to_char_offset(offsets: dict | bool, position: int) -> int:
    """Map a UTF-16 code unit offset back to a Python string index."""
    if offsets:
        return offsets["utf16_chars"].get(position, position)

    return position


def to_utf16_offset(offsets: dict | bool, position: int) -> int:
    """Map a Python string index to a UTF-16 code unit offset."""
    if offsets:
        return offsets["chars"][position]

    return position


def sentence_char_ranges(text: str) -> list[tuple[int, int]]:
    """Sentence spans over the text, as (start, end) character indexes."""
    ranges = []
    start = 0
    for position, char in enumerate(text):
        if char in SENTENCE_BOUNDARIES:
            if text[start : position + 1].strip():
                ranges.append((start, position + 1))
            start = position + 1
        elif char == " " and start == position:
            start = position + 1

    if start < len(text) and text[start:].strip():
        ranges.append((start, len(text)))

    return ranges


def fetch_sentence(text: str, start: int, end: int) -> str:
    sentence_start = 0
    for boundary in SENTENCE_BOUNDARIES:
        position = text.rfind(boundary, 0, start)
        if position >= 0:
            sentence_start = max(sentence_start, position + 1)

    sentence_end = len(text)
    for boundary in SENTENCE_BOUNDARIES:
        position = text.find(boundary, end)
        if position >= 0:
            sentence_end = min(sentence_end, position + 1)

    return text[sentence_start:sentence_end].strip()


def build_match(result: ResultOut, text: str, offsets: dict | bool) -> LTMatch:
    # Internal results carry UTF-16 code unit offsets (what LanguageTool
    # clients expect too); map them back to Python string indexes for slicing.
    start = to_char_offset(offsets, result.start)
    end = to_char_offset(offsets, result.end)

    context_start = max(0, start - CONTEXT_RADIUS)
    context_end = min(len(text), end + CONTEXT_RADIUS)

    if offsets:
        context_offset = offsets["chars"][start] - offsets["chars"][context_start]
    else:
        context_offset = start - context_start

    replacements = []
    for alternative in result.alternatives or []:
        if alternative.remove:
            replacements.append(LTReplacement(value=""))
        elif alternative.text:
            replacements.append(LTReplacement(value=alternative.text))

    category = result.category or "witty"
    subcategory = result.subcategory or category

    explanation = result.explanation.text if result.explanation else None
    message = explanation or result.label or subcategory

    urls = None
    if result.explanation and result.explanation.url:
        urls = [LTUrl(value=result.explanation.url)]

    is_orthography = category == "orthography"

    return LTMatch(
        message=message,
        shortMessage=result.label or "",
        offset=result.start,
        length=result.end - result.start,
        replacements=replacements,
        context=LTContext(
            text=text[context_start:context_end],
            offset=context_offset,
            length=result.end - result.start,
        ),
        sentence=fetch_sentence(text, start, end),
        type=LTMatchType(typeName="Other" if is_orthography else "Hint"),
        rule=LTRule(
            id="WITTY_" + subcategory.upper(),
            description=result.label or subcategory.replace("_", " "),
            issueType="misspelling" if is_orthography else "style",
            category=LTCategory(
                id=category.upper(),
                name=category.replace("_", " ").capitalize(),
            ),
            urls=urls,
        ),
    )


def build_response(
    context: AppContext,
    locale: str,
    matches: list[LTMatch],
    limit_reached: bool = False,
    sentence_ranges: list[list[int]] | None = None,
) -> LTCheckResponse:
    sentence_ranges = sentence_ranges or []

    return LTCheckResponse(
        software=LTSoftware(
            name="Witty NLP API",
            version=context.version,
            buildDate="",
            apiVersion=1,
            premium=False,
            status="",
        ),
        warnings=LTWarnings(incompleteResults=limit_reached),
        language=LTLanguage(
            name=LOCALE_NAMES.get(locale, locale),
            code=locale,
            detectedLanguage=LTDetectedLanguage(
                name=LOCALE_NAMES.get(locale, locale),
                code=locale,
                confidence=1.0,
            ),
        ),
        matches=matches,
        sentenceRanges=sentence_ranges,
        extendedSentenceRanges=[
            LTExtendedSentenceRange(
                from_=start,
                to=end,
                detectedLanguages=[LTDetectedLanguageRate(language=locale, rate=1.0)],
            )
            for start, end in sentence_ranges
        ],
    )


@router.post(
    "/check",
    response_model=LTCheckResponse,
    response_model_exclude_none=True,
)
async def lt_check(
    request: Request,
    text: str | None = Form(None),
    data: str | None = Form(None),
    language: str = Form("auto"),
    username: str | None = Form(None),
    apiKey: str | None = Form(None),
    password: str | None = Form(None),
    tokenV2: str | None = Form(None),
    motherTongue: str | None = Form(None),
    preferredVariants: str | None = Form(None),
    disabledCategories: str | None = Form(None),
    context: AppContext = Depends(get_app_context),
):
    if text is None and data is None:
        return PlainTextResponse(
            "Error: Missing 'text' or 'data' parameter.", status_code=400
        )

    # An empty `text` field must not shadow `data`: clients are seen sending
    # both, with the actual content in `data`.
    markup_spans = []
    if not text and data is not None:
        try:
            text, markup_spans = text_from_data(data)
        except (ValueError, AttributeError, TypeError):
            return PlainTextResponse(
                "Error: Could not parse 'data' parameter.", status_code=400
            )

        if not text:
            context.logger.debug("lt_check no text extracted from data=%.300r", data)

    lang = resolve_lang(language)
    if lang is None:
        return PlainTextResponse(
            f"Error: '{language}' is not a language code known to this server.",
            status_code=400,
        )

    config = Config()
    if preferredVariants:
        config.preferred_variants = [
            variant.strip() for variant in preferredVariants.split(",")
        ]

    if motherTongue:
        try:
            config.primary_language = LangVariantType(motherTongue)
        except ValueError:
            pass

    if disabledCategories:
        config.disabled_categories = [
            category.strip().lower() for category in disabledCategories.split(",")
        ]

    check_request_in = CheckRequestIn(text=text, lang=lang, config=config)
    client = Client.parse("lt:0.0.0")

    user_email = await fetch_user(
        request, context.settings, context.redis, context.http
    )
    if user_email is None and apiKey:
        user_email = context.redis.get_api_key_email(apiKey)

        # LanguageTool answers an invalid API key with a 401 AuthException;
        # do the same so a mistyped key surfaces in the client instead of
        # silently checking nothing. Deployments that do not require auth
        # keep LanguageTool's fall-back-to-anonymous behavior instead.
        if user_email is None and context.settings.require_auth:
            return PlainTextResponse(
                "Error: org.languagetool.server.AuthException: "
                "Invalid API key or username.",
                status_code=401,
            )

    if user_email is None and (password or tokenV2) and context.settings.require_auth:
        return PlainTextResponse(
            "Error: org.languagetool.server.AuthException: "
            "This server only supports authentication via 'apiKey'; "
            "'password' and 'tokenV2' logins are not available.",
            status_code=401,
        )

    configs = await fetch_configs_for_request(check_request_in, user_email, context)

    context.redis.store_metrics(request, configs, "lt", "check")
    context.redis.store_request_log(
        check_request_in, user_email, request, configs, "lt", "check"
    )

    # Mirror the native check endpoint: a request that resolves to no user
    # gets an empty result set rather than a 4xx, so signed-out or
    # unauthenticated clients keep working and just get nothing back.
    if not configs and context.settings.require_auth:
        context.logger.debug("lt_check language=%r no user resolved", language)
        locale = language if lang != LangWithAutoType.AUTO else "en-US"
        return build_response(context, locale, [])

    checked_text, language_obj, limit_reached = fetch_text(
        check_request_in, context.langs, context
    )

    if language_obj is None and lang == LangWithAutoType.AUTO:
        # Detection fails on short or heavily misspelled texts. A LanguageTool
        # server always checks with its best guess, so fall back to the first
        # supported preferred variant rather than answering with nothing.
        fallback = "en-US"
        for variant in check_request_in.config.preferred_variants:
            if variant in context.languages:
                fallback = variant
                break

        language_obj = context.languages.get(fallback)
        context.logger.debug(
            "lt_check language=%r not detected, fell back to %s", language, fallback
        )

    if language_obj is None:
        # A supported but not locally loaded language: answer with zero
        # matches instead of an error, LanguageTool clients check on every
        # edit and an error would surface each time.
        context.logger.debug("lt_check language=%r not available", language)
        locale = language if lang != LangWithAutoType.AUTO else "en-US"
        response = build_response(context, locale, [])
        response.language.detectedLanguage.confidence = 0.0
        return response

    results = await apply_language_rules(
        client, check_request_in.config, configs, language_obj, checked_text, context
    )

    if isinstance(results, Result):
        return PlainTextResponse(
            "Error: " + json.dumps(results.detail), status_code=400
        )

    offsets = utf16_offsets(checked_text)

    matches = []
    for result in results:
        start = to_char_offset(offsets, result.start)
        end = to_char_offset(offsets, result.end)
        if any(
            start < span_end and end > span_start
            for span_start, span_end in markup_spans
        ):
            continue

        matches.append(build_match(result, checked_text, offsets))

    sentence_ranges = [
        [to_utf16_offset(offsets, start), to_utf16_offset(offsets, end)]
        for start, end in sentence_char_ranges(checked_text)
    ]

    response = build_response(
        context,
        language_obj.locale,
        matches,
        limit_reached=limit_reached,
        sentence_ranges=sentence_ranges,
    )

    context.logger.debug(
        "lt_check language=%r locale=%s text_chars=%d data=%s matches=%d",
        language,
        language_obj.locale,
        len(checked_text),
        data is not None,
        len(matches),
    )

    context.redis.store_response_log(user_email, response)

    return response


@router.get("/languages", response_model=list[LTLanguageItem])
async def lt_languages() -> list[LTLanguageItem]:
    return [
        LTLanguageItem(
            name=LOCALE_NAMES.get(locale.value, locale.value),
            code=locale.value[0:2],
            longCode=locale.value,
        )
        for locale in Config._supported_locales.default
    ]


@router.get("/maxtextlength")
async def lt_maxtextlength(
    context: AppContext = Depends(get_app_context),
) -> PlainTextResponse:
    return PlainTextResponse(str(context.settings.text_max_length))


@router.get("/info")
async def lt_info(context: AppContext = Depends(get_app_context)) -> dict:
    return {
        "software": {
            "name": "Witty NLP API",
            "version": context.version,
            "buildDate": "",
            "apiVersion": 1,
            "premium": False,
        }
    }


# Personal dictionaries are not supported; these stubs answer in the
# LanguageTool response shapes so clients that sync a dictionary get an
# honest "nothing here / not stored" instead of a 404 error dialog.
@router.get("/words")
async def lt_words() -> dict:
    return {"words": []}


@router.post("/words/add")
async def lt_words_add() -> dict:
    return {"added": False}


@router.post("/words/delete")
async def lt_words_delete() -> dict:
    return {"deleted": False}
