"""Utility routes for basic API operations."""

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.encoders import jsonable_encoder
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.exceptions import RequestValidationError
from starlette.responses import RedirectResponse

from app.models import LangType
from app.dependencies import (
    fetch_current_username,
    fetch_management_username,
    get_app_context,
)
from app.context import AppContext
from app.settings import get_settings, Settings
from app.text_utils import parse_word_type

router = APIRouter()


@router.get("/health")
async def get_health(
    check_external: bool = False, context: AppContext = Depends(get_app_context)
) -> dict:
    health = {}

    langs = {
        LangType.EN: "Hello guys",
        LangType.DE: "Hallo Kunde",
        LangType.FR: "Je m'appelle Luc",
    }

    for lang in context.langs:
        try:
            context.model.fetch_tokens(lang, langs[lang])
            health["model_" + lang] = True
        except Exception:
            health["model_" + lang] = False

    if check_external:
        try:
            languagetool_health = await context.http.fetch_json_get(
                context.settings.languagetool_api + "/healthcheck",
                {},
                {},
                "LanguageTool",
                context.settings.languagetool_verify_ssl,
                False,
            )

            health["spelling"] = languagetool_health == "OK"
        except Exception:
            health["spelling"] = False

        try:
            health["config"] = context.redis.db.ping()
        except Exception:
            health["config"] = False

    content = jsonable_encoder(health)

    for key in health:
        if not health[key]:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=content,
            )

    return content


@router.get("/lt", include_in_schema=not get_settings().is_prod)
def get_lt(
    username: str = Depends(fetch_management_username),
    context: AppContext = Depends(get_app_context),
) -> str:
    return context.settings.languagetool_api


@router.get("/settings", include_in_schema=not get_settings().is_prod)
def get_app_settings(
    username: str = Depends(fetch_management_username),
    context: AppContext = Depends(get_app_context),
) -> Settings:
    return context.settings


@router.get("/docs", include_in_schema=False)
def get_swagger_documentation(
    username: str = Depends(fetch_current_username),
):  # pragma: no cover
    return get_swagger_ui_html(openapi_url="/openapi.json", title="docs")


@router.get("/openapi.json", include_in_schema=False)
def get_openapi_json(request: Request) -> dict:  # pragma: no cover
    app = request.app
    return get_openapi(title=app.title, version=app.version, routes=app.routes)


@router.get("/", include_in_schema=False)
def get_root(context: AppContext = Depends(get_app_context)):
    if (
        not context.settings.is_prod and context.settings.testing is False
    ):  # pragma: no cover
        return RedirectResponse(url="/docs", status_code=302)

    return "Witty NLP API: https://witty.works"


@router.get(
    "/save_openapi_json",
    include_in_schema=not get_settings().is_prod,
)
def get_save_openapi_json(
    request: Request, username: str = Depends(fetch_current_username)
):  # pragma: no cover
    openapi_data = request.app.openapi()
    for path in openapi_data["paths"].copy():
        if "v2.0" not in path:
            del openapi_data["paths"][path]

    with open("openapi.json", "w") as file:
        json.dump(openapi_data, file, indent=4, sort_keys=True)


@router.get("/lemmatize")
async def get_lemmatize(
    text: str,
    lang: LangType,
    all: bool = False,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_current_username),
) -> str | tuple[str, ...] | None:
    tokens = context.model.fetch_tokens(lang, text)
    if all:
        return tuple([i.lemma_ for i in tokens])

    if len(tokens) != 1:
        return None

    return tokens[0].lemma_


@router.get("/tokenize")
async def get_tokenize(
    text: str,
    lang: LangType,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_current_username),
) -> tuple[str, ...]:
    return context.model.tokenize(text, lang)


@router.get("/parse-word-types")
async def get_parse_word_types(
    text: str,
    word_types: str,
    lang: LangType,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_current_username),
) -> list[dict[str, Any]]:
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
