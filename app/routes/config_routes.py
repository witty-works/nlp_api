"""
Configuration Management Routes
Handles organization and user configuration CRUD operations.
"""

from fastapi import APIRouter, Depends, status

from app.context import AppContext
from app.dependencies import fetch_current_username, get_app_context
from app.models import (
    ConfResponse,
    ErrorMessage,
    OrganizationConfRequest,
    UserConfRequest,
    UserConfResponse,
)
from app.config_manager import (
    parse_term_replacements,
    fetch_user_organization_configs,
)
from app.models import PrettyJSONResponse

router = APIRouter()


# Organization Configuration Routes


@router.post(
    "/organization/configs",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def post_organization_configs(
    organization_configs: OrganizationConfRequest,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_current_username),
):
    organization_configs.term_replacements = parse_term_replacements(
        organization_configs.term_replacements, context
    )
    context.redis.db.set(
        organization_configs.id, organization_configs.model_dump_json()
    )


@router.delete(
    "/organization/configs",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_organization_configs(
    organization_id: str,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_current_username),
):
    context.redis.db.delete(organization_id)


@router.get(
    "/organization/configs",
    response_model=ConfResponse,
    response_model_exclude_none=True,
    responses={404: {"model": ErrorMessage}},
)
async def get_organization_configs(
    organization_id: str,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_current_username),
):
    return await context.redis.fetch_organization_configs_from_redis(organization_id)


# User Configuration Routes


@router.post(
    "/user/configs",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def post_user_configs(
    user_configs: UserConfRequest,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_current_username),
):
    user_configs.term_replacements = parse_term_replacements(
        user_configs.term_replacements, context
    )
    context.redis.db.set(
        context.redis.get_user_id(user_configs.email), user_configs.model_dump_json()
    )


@router.delete(
    "/user/configs",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_user_configs(
    email: str,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_current_username),
):
    context.redis.db.delete(context.redis.get_user_id(email))


@router.get(
    "/user/configs",
    response_model=UserConfResponse,
    response_model_exclude_none=True,
    responses={404: {"model": ErrorMessage}},
)
async def get_user_configs(
    email: str,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_current_username),
):
    return await fetch_user_organization_configs(email, context)


# User Logs Route


@router.get(
    "/user/logs",
    response_class=PrettyJSONResponse,
)
async def get_user_logs(
    email: str,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_current_username),
):
    return context.redis.get_user_logs(email)
