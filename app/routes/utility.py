"""Utility routes for basic API operations."""

import base64
import hashlib
import json
import re
from functools import lru_cache
from typing import Any

import spacy

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.encoders import jsonable_encoder
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.exceptions import RequestValidationError
from starlette.responses import HTMLResponse, RedirectResponse

from app.llm_provider import public_model_name
from app.models import LangType
from app.dependencies import (
    development_only,
    fetch_current_username,
    fetch_management_username,
    get_app_context,
)
from app.context import AppContext
from app.settings import get_settings, public_url
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

    # Without LANGUAGETOOL_API there is no LanguageTool to ask.
    if check_external and context.settings.languagetool_api:
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

    if check_external:
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

    # Information only, outside the checks above: a mismatch only warns by
    # default, a fresh worker has served nothing yet, and each worker keeps
    # its own. Only model names, never a machine or host.
    if context.settings.llm_model:
        content["llm"] = {
            "configured": public_model_name(context.settings.llm_model),
            "served": context.prompt.last_served_model,
            "matched": context.prompt.last_model_matched,
        }

    return content


@router.get("/version")
async def get_version(context: AppContext = Depends(get_app_context)) -> dict:
    """Identify exactly what this service runs: app version, git revision,
    spaCy version, the loaded model versions and the rules file (with
    whether it is the image's own, see Db.rules_info). Clients stamp evaluation
    state with this so results computed against an older build are
    recognizably stale instead of silently outdated."""
    models = {}
    for lang, model in context.model.models.items():
        meta = model.meta
        models[lang] = {
            "name": "%s_%s" % (meta.get("lang", lang), meta.get("name", "unknown")),
            "version": meta.get("version", "unknown"),
        }

    return {
        "app_version": context.version,
        "git_revision": context.settings.git_revision,
        "spacy_version": spacy.__version__,
        "models": models,
        "rules": context.db.rules_info(),
    }


@router.get("/languagetool_api", include_in_schema=not get_settings().is_prod)
def get_languagetool_api(
    username: str = Depends(fetch_management_username),
    context: AppContext = Depends(get_app_context),
) -> str:
    return public_url(context.settings.languagetool_api)


@router.get("/settings", include_in_schema=not get_settings().is_prod)
def get_app_settings(
    username: str = Depends(fetch_management_username),
    context: AppContext = Depends(get_app_context),
) -> dict[str, Any]:
    """The settings that help debug a deployment, without its secrets."""
    return context.settings.debug_view()


# Swagger UI for /docs, at an exact version and checked by its hash
# (Subresource Integrity), so the CDN cannot hand the page other code. The
# hashes are of the files as published on npm; for another version, compute
# them from its files:
#   curl -s URL | openssl dgst -sha384 -binary | openssl base64 -A
SWAGGER_UI_URL = "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.34.1/"
SWAGGER_JS = (
    SWAGGER_UI_URL + "swagger-ui-bundle.js",
    "sha384-XFYN47VzPiDY6qPtxYKg0nqUeW/upo20xf1j2SUE7gT/i35FJB4cuS/71Iegzk8Z",
)
SWAGGER_CSS = (
    SWAGGER_UI_URL + "swagger-ui.css",
    "sha384-4c3vsE5f+trhFyHrFrLM1fFGUn531NIaC7dcqEWIJdoRQJ5CkJbSuSCwXLpaS1KF",
)
SWAGGER_FAVICON = "https://fastapi.tiangolo.com/img/favicon.png"


@lru_cache(maxsize=1)
def swagger_ui_page() -> tuple[str, str]:
    """The /docs page with its assets pinned, and the policy that lets it run
    and nothing else: the CDN only for the two files, the inline script that
    starts Swagger UI only by its hash. Styles stay 'unsafe-inline', as
    Swagger UI sets them on its elements."""
    page = bytes(
        get_swagger_ui_html(
            openapi_url="/openapi.json",
            title="docs",
            swagger_js_url=SWAGGER_JS[0],
            swagger_css_url=SWAGGER_CSS[0],
            swagger_favicon_url=SWAGGER_FAVICON,
        ).body
    ).decode("utf-8")
    pinned = page.replace(
        f'<script src="{SWAGGER_JS[0]}"></script>',
        f'<script src="{SWAGGER_JS[0]}" integrity="{SWAGGER_JS[1]}"'
        ' crossorigin="anonymous"></script>',
    ).replace(
        f'href="{SWAGGER_CSS[0]}">',
        f'href="{SWAGGER_CSS[0]}" integrity="{SWAGGER_CSS[1]}"'
        ' crossorigin="anonymous">',
    )
    # A FastAPI that writes the tags differently would drop the integrity
    # check silently; fail instead.
    if pinned.count('integrity="') != 2:
        raise RuntimeError("could not pin the Swagger UI assets in /docs")

    inline = re.findall(r"<script>(.*?)</script>", pinned, re.DOTALL)
    script_hashes = " ".join(
        "'sha256-"
        + base64.b64encode(hashlib.sha256(script.encode("utf-8")).digest()).decode()
        + "'"
        for script in inline
    )
    policy = "; ".join(
        [
            "default-src 'self'",
            f"script-src 'self' {SWAGGER_JS[0]} {script_hashes}",
            f"style-src 'self' 'unsafe-inline' {SWAGGER_CSS[0]}",
            "img-src 'self' data: https://fastapi.tiangolo.com",
            "connect-src 'self'",
            "object-src 'none'",
            "base-uri 'none'",
            "frame-ancestors 'none'",
        ]
    )

    return pinned, policy


@router.get("/docs", include_in_schema=False)
def get_swagger_documentation(
    username: str = Depends(fetch_current_username),
) -> HTMLResponse:
    page, policy = swagger_ui_page()

    return HTMLResponse(page, headers={"Content-Security-Policy": policy})


@router.get("/openapi.json", include_in_schema=False)
def get_openapi_json(request: Request) -> dict:  # pragma: no cover
    app = request.app
    return get_openapi(title=app.title, version=app.version, routes=app.routes)


@router.get("/", include_in_schema=False)
def get_root(context: AppContext = Depends(get_app_context)):
    if context.settings.root_redirect:
        return RedirectResponse(url=context.settings.root_redirect, status_code=302)

    if (
        not context.settings.is_prod and context.settings.testing is False
    ):  # pragma: no cover
        return RedirectResponse(url="/docs", status_code=302)

    return "Witty NLP API: https://witty.works"


@router.get(
    "/save_openapi_json",
    include_in_schema=not get_settings().is_prod,
    dependencies=[Depends(development_only)],
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


@router.get(
    "/lemmatize",
    include_in_schema=not get_settings().is_prod,
    dependencies=[Depends(development_only)],
)
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


@router.get(
    "/tokenize",
    include_in_schema=not get_settings().is_prod,
    dependencies=[Depends(development_only)],
)
async def get_tokenize(
    text: str,
    lang: LangType,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_current_username),
) -> tuple[str, ...]:
    return context.model.tokenize(text, lang)


@router.get(
    "/parse-word-types",
    include_in_schema=not get_settings().is_prod,
    dependencies=[Depends(development_only)],
)
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
