"""
Authentication Routes
Handles authentication, authorization, and API key management.
"""

from typing import Union

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer
from fastapi.security.api_key import APIKeyHeader

from app.context import AppContext
from app.dependencies import fetch_current_username, get_app_context
from app.models import BaseRequestIn, CheckRequestIn, ErrorMessage, ResultConf, Client
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


@router.get(
    "/api_key",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={404: {"model": ErrorMessage}},
)
async def get_api_key(
    api_key: str,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_current_username),
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
    username: str = Depends(fetch_current_username),
):
    context.redis.set_api_key(api_key, email)


@router.delete(
    "/api_key",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_api_key(
    api_key: str,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_current_username),
):
    context.redis.delete_api_key(api_key)
