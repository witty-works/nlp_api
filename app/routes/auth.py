"""
Authentication Routes
Handles authentication, authorization, and API key management.
"""

from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
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
    LangVariantType,
    LangWithAutoType,
    ResultConf,
    Client,
)
from app.version_validators import client_version
from app.config_manager import fetch_configs_for_request, fetch_result_conf
from app.auth_service import fetch_user

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
    client_version(client)

    user_email = await fetch_user(
        request, context.settings, context.redis, context.http
    )
    configs = (
        await fetch_configs_for_request(CheckRequestIn(text=""), user_email, context)
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


@router.get("/v2.0/categories", response_model=CategoriesOut)
async def get_categories_2_0(
    response: Response,
    locale: LangVariantType = LangVariantType.enUS,
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
    "gendered_roles_format",
)


@router.get("/v2.0/config-options", response_model=ConfigOptionsOut)
async def get_config_options_2_0(
    response: Response,
    locale: LangVariantType = LangVariantType.enUS,
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


@router.get(
    "/api_key",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorMessage}},
)
async def get_api_key(
    api_key: str,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_management_username),
):
    email = context.redis.get_api_key_email(api_key)
    if not email:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="API key not found"
        )

    return email


@router.post(
    "/api_key",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def post_api_key(
    api_key: str,
    email: str,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_management_username),
):
    context.redis.set_api_key(api_key, email)


@router.delete(
    "/api_key",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_api_key(
    api_key: str,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_management_username),
):
    context.redis.delete_api_key(api_key)
