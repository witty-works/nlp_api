"""
Authentication Routes
Handles authentication, authorization, and API key management.
"""

from typing import Union

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPBearer
from fastapi.security.api_key import APIKeyHeader

from app.categories import get_category_list, get_config_option_labels_for
from app.context import AppContext
from app.dependencies import fetch_management_username, get_app_context
from app.models import (
    BaseRequestIn,
    CategoriesOut,
    CheckRequestIn,
    Config,
    ConfigOptionsOut,
    ErrorMessage,
    FeatureOut,
    FeaturesOut,
    LangType,
    LangVariantType,
    LangWithAutoType,
    ResultConf,
    Client,
)
from app.version_validators import client_version
from app.config_manager import (
    fetch_configs_for_request,
    fetch_result_conf,
    llm_alternatives_allowed,
    llm_available,
)
from app.auth_service import fetch_user
from app.api_keys import (
    ApiKeyEntry,
    ApiKeysIn,
    SyncResult,
    sync,
    valid_email,
    valid_key,
    validate_entries,
)

router = APIRouter()


@router.post(
    "/v2.0/auth",
    response_model=Union[ResultConf, dict, None],
    response_model_exclude_none=True,
    dependencies=[
        Depends(HTTPBearer(auto_error=False)),
        Depends(APIKeyHeader(name="x-key", auto_error=False)),
    ],
)
async def post_auth_2_0(
    request: Request,
    check_request_in: BaseRequestIn | None = None,
    context: AppContext = Depends(get_app_context),
):
    client = Client.parse(
        check_request_in.client if check_request_in is not None else None
    )
    client_version(client, context.settings.minimum_versions)

    user_email = await fetch_user(
        request, context.settings, context.redis, context.http
    )
    configs = (
        await fetch_configs_for_request(CheckRequestIn(text=""), user_email, context)
        if user_email
        else {}
    )

    context.redis.store_metrics(request, configs, "2.0", "auth")

    # No credential, or one that resolves to nobody: 401. A user this
    # deployment has no config for is known but not let in: 403.
    if user_email is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
        )
    if configs == {}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
        )

    config = fetch_result_conf(configs)

    if "team_analytics" in configs and not configs["team_analytics"]:
        config.organization_id = None

    return config


@router.get("/v2.0/categories", response_model=CategoriesOut)
async def get_categories_2_0(
    response: Response,
    locale: LangVariantType | LangType = LangVariantType.enUS,
    context: AppContext = Depends(get_app_context),
):
    """The category keys a client may put in `config.disabled_categories`.

    `/v2.0/auth` only reports categories the dashboard synced into the user's
    organisation config, so a deployment running on API keys alone has no list
    to offer its users. This one is derived from the training data and is
    therefore the same in either deployment.

    Unauthenticated on purpose: the answer is the same for everyone, says
    nothing about any user, and is already public at
    https://www.witty.works/en/categories.html. That also makes it cacheable,
    so clients and any proxy in front of the API can keep a copy rather than
    asking again per user.
    """
    response.headers["Cache-Control"] = "public, max-age=3600"

    language = context.languages[LangWithAutoType(locale.value)]
    categories, groups = get_category_list(language)

    return CategoriesOut(categories=categories, groups=groups)


# The config fields whose accepted values a client cannot guess: each is a
# closed set of tokens rather than a boolean or free text.
CONFIG_OPTION_FIELDS = (
    "german_gender_ending",
    "french_gender_separator",
    "french_gender_suffix",
    "gendered_roles_format",
)


@router.get(
    "/v2.0/features",
    response_model=FeaturesOut,
    response_model_exclude_none=True,
    dependencies=[
        Depends(HTTPBearer(auto_error=False)),
        Depends(APIKeyHeader(name="x-key", auto_error=False)),
    ],
)
async def get_features_2_0(
    request: Request,
    response: Response,
    context: AppContext = Depends(get_app_context),
):
    """What this deployment offers, and with a key, what that key may use.

    One place to discover the features that differ between deployments, so a
    client can show or hide them instead of finding out from a refused
    request. Without a credential it reports `available` only, the same for
    everyone, and is public like /v2.0/categories so a client can render its
    UI before a key exists. With one it adds `allowed` where some keys are
    refused a feature; a credential that does not resolve is a 401 rather
    than an anonymous answer, so a client can tell a wrong key from none.

    - `llm`: the language model behind the prompt and AI suggestions
      (LLM_MODEL; LLM_ACCESS and LLM_ALLOWED_USERS decide `allowed`).
    - `spelling_grammar`: LanguageTool's findings (LANGUAGETOOL_API).
    - `languages`: the languages this server checks (MODELS).
    """
    sent = "x-key" in request.headers or request.headers.get(
        "authorization", ""
    ).lower().startswith("bearer")
    user_email = (
        await fetch_user(request, context.settings, context.redis, context.http)
        if sent
        else None
    )
    if sent and user_email is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A valid API key is required in the x-key header.",
        )

    settings = context.settings
    llm = FeatureOut(available=llm_available(settings))
    if sent:
        llm.allowed = llm_alternatives_allowed(settings, user_email)

    # The same for everyone without a key; per key, it must not be shared.
    response.headers["Cache-Control"] = (
        "private, no-store" if sent else "public, max-age=300"
    )
    # One URL, answered per credential: without Vary a browser serves the
    # cached keyless answer, which has no `allowed`, to a request with a key.
    response.headers["Vary"] = "x-key, Authorization"

    return FeaturesOut(
        features={
            "llm": llm,
            "spelling_grammar": FeatureOut(available=bool(settings.languagetool_api)),
            "languages": FeatureOut(
                available=True, values=sorted(context.model.models)
            ),
        }
    )


@router.get("/v2.0/config-options", response_model=ConfigOptionsOut)
async def get_config_options_2_0(
    response: Response,
    locale: LangVariantType | LangType = LangVariantType.enUS,
):
    """The values `config.german_gender_ending` and its siblings accept.

    Same problem as the category list: an options page has to offer the gender
    ending and role formats this API understands, and a deployment without a
    dashboard has nowhere else to learn them. The values are derived from the
    request model, so they answer for the running version rather than for
    whatever was documented.

    Labels come from training_data/config_options.json, copied from the
    dashboard alongside categories.json, so both surfaces name a setting the
    same way. A value the dashboard has no wording for is returned without a
    label and clients show the value itself.

    Unauthenticated and cacheable for the same reason as `/v2.0/categories`: the
    answer is the same for everyone and says nothing about any user.
    """
    response.headers["Cache-Control"] = "public, max-age=3600"

    lang = locale.value.split("-")[0]
    options = Config.field_options(*CONFIG_OPTION_FIELDS)

    for field, option in options.items():
        labels = get_config_option_labels_for(field, lang)
        # Only label values this version actually accepts, so a stale entry in
        # the copied file cannot advertise a value the API would reject.
        option["labels"] = {
            value: labels[value] for value in option["values"] if value in labels
        }

    return ConfigOptionsOut(options=options)


def _api_key_from(body: dict, with_email: bool) -> tuple[str, str]:
    """The key (and email) of a /api_key request, checked with the key file's
    rules (app/api_keys.py) rather than by a model, so that a 422 cannot echo
    the key back."""
    api_key = body.get("api_key") if isinstance(body, dict) else None
    email = body.get("email") if isinstance(body, dict) else None
    try:
        api_key = valid_key(api_key if isinstance(api_key, str) else "")
        email = (
            valid_email(email if isinstance(email, str) else "") if with_email else ""
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        )
    return api_key, email


API_KEY_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "required": ["api_key", "email"],
                    "properties": {
                        "api_key": {"type": "string", "minLength": 20},
                        "email": {"type": "string", "format": "email"},
                    },
                }
            }
        },
    }
}


@router.post(
    "/api_key",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={409: {"model": ErrorMessage}, 422: {"model": ErrorMessage}},
    openapi_extra=API_KEY_BODY,
)
async def post_api_key(
    body: dict = Body(..., include_in_schema=False),
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_management_username),
):
    """Map a key to an email. The key goes in the body, never the URL, which
    access logs keep. A key that already belongs to another email is refused
    rather than taken over."""
    api_key, email = _api_key_from(body, with_email=True)
    current = context.redis.get_api_key_email(api_key)
    if current is not None and current != email:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This API key belongs to another email",
        )
    context.redis.set_api_key(api_key, email)


@router.delete(
    "/api_key",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorMessage}, 422: {"model": ErrorMessage}},
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["api_key"],
                        "properties": {"api_key": {"type": "string"}},
                    }
                }
            },
        }
    },
)
async def delete_api_key(
    body: dict = Body(..., include_in_schema=False),
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_management_username),
):
    api_key = body.get("api_key") if isinstance(body, dict) else None
    if not isinstance(api_key, str) or not context.redis.get_api_key_email(api_key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="API key not found"
        )
    context.redis.delete_api_key(api_key)


@router.put(
    "/api_keys",
    response_model=SyncResult,
    responses={409: {"model": ErrorMessage}, 422: {"model": ErrorMessage}},
    # Validated in the handler, so a 422 cannot echo a key back; the schema
    # is still documented.
    openapi_extra={
        "requestBody": {
            "content": {"application/json": {"schema": ApiKeysIn.model_json_schema()}},
            "required": True,
        }
    },
)
async def put_api_keys(
    body: dict = Body(..., include_in_schema=False),
    dry_run: bool = False,
    allow_empty: bool = False,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_management_username),
):
    """Make the synced API keys match the local key file (see app/api_keys.py
    and bin/sync_api_keys.py): add new keys, revoke the ones this endpoint
    synced before that are no longer listed, and replace each email's config.
    Keys minted any other way are left alone. With `dry_run`, only report
    what would change. An empty list is refused unless `allow_empty`, since it
    revokes every synced key. The response names emails, never keys."""
    try:
        entries = validate_entries(body)
        result = sync(context.redis, entries, dry_run, allow_empty)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(e)
        )

    if result.conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Keys already in use for other emails, nothing synced: "
            + ", ".join(sorted(set(result.conflicts))),
        )

    result.warnings = sync_warnings(entries, context)

    return result


def sync_warnings(entries: list[ApiKeyEntry], context: AppContext) -> list[str]:
    """What the sync writes but the API will not act on, or should know."""
    warnings = []
    if entries and not context.settings.api_key_hmac_key:
        warnings.append(
            "API_KEY_HMAC_KEY is not set: the keys are stored in Redis as written"
        )
    seen = set()
    for entry in entries:
        if entry.email in seen:
            continue
        seen.add(entry.email)

        if (entry.config or entry.force) and context.redis.db.exists(
            context.redis.get_user_id(entry.email)
        ):
            warnings.append(
                f"{entry.email}: config ignored, a config synced from the "
                "dashboard for this email wins"
            )

        wants_llm = entry.force.get(
            "llm_alternatives", entry.config.get("llm_alternatives")
        )
        if wants_llm and not llm_alternatives_allowed(context.settings, entry.email):
            warnings.append(
                f"{entry.email}: llm_alternatives has no effect, LLM_ACCESS "
                "(or LLM_ALLOWED_USERS) does not allow it"
            )

    return warnings
