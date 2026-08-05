"""
Rephrase Routes
Handles text rephrasing using LLM alternatives.
"""

from typing import Union

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.security import HTTPBearer
from fastapi.security.api_key import APIKeyHeader

from app.context import AppContext
from app.dependencies import fetch_current_username, get_app_context
from app.settings import get_settings
from app.models import RephraseRequestIn, RephrasesOut, Result, Client
from app.version_validators import (
    client_version,
    rephrase_api_version,
    REPHRASE_API_VERSION,
)
from app.config_manager import fetch_configs_for_request
from app.auth_service import fetch_user

router = APIRouter()


@router.post(
    "/debug/rephrase",
    response_model=Union[RephrasesOut, Result],
    response_model_exclude_none=True,
    dependencies=[
        Depends(HTTPBearer(auto_error=False)),
        Depends(APIKeyHeader(name="x-key", auto_error=False)),
    ],
    include_in_schema=not get_settings().is_prod,
)
async def post_debug_rephrase(
    request: Request,
    response: Response,
    rephrase_request_in: RephraseRequestIn,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_current_username),
) -> Union[RephrasesOut, Result]:
    """Debug endpoint for rephrasing text.

    Args:
        request: FastAPI request object
        response: FastAPI response object
        rephrase_request_in: Rephrase request data
        username: Authenticated username

    Returns:
        Rephrased alternatives or error result
    """
    return await rephrase_sentence(request, response, rephrase_request_in, context)


@router.post(
    f"/v{REPHRASE_API_VERSION}/rephrase",
    response_model=Union[RephrasesOut, Result],
    response_model_exclude_none=True,
    dependencies=[
        Depends(HTTPBearer(auto_error=False)),
        Depends(APIKeyHeader(name="x-key", auto_error=False)),
    ],
)
async def post_rephrase_v1_0(
    request: Request,
    response: Response,
    rephrase_request_in: RephraseRequestIn,
    context: AppContext = Depends(get_app_context),
) -> Union[RephrasesOut, Result]:
    return await rephrase_sentence(
        request, response, rephrase_request_in, context, REPHRASE_API_VERSION
    )


async def rephrase_sentence(
    request: Request,
    response: Response,
    rephrase_request_in: RephraseRequestIn,
    context: AppContext,
    version: str | None = None,
) -> Union[RephrasesOut, Result]:
    client = Client.parse(rephrase_request_in.client)
    client_version(client)

    if version is not None:
        if rephrase_request_in.model is not None:
            return Result.factory("Model can only be set in debug mode")

        rephrase_api_version(version)

        user_email = await fetch_user(
            request, context.settings, context.redis, context.http
        )
        if user_email is None:
            response.status_code = status.HTTP_401_UNAUTHORIZED
            return Result.factory("User not found")

        configs = await fetch_configs_for_request(
            rephrase_request_in, user_email, context
        )

        if (
            rephrase_request_in.config.plan is None
            or not rephrase_request_in.config.plan.startswith("witty_")
        ):
            response.status_code = status.HTTP_401_UNAUTHORIZED
            return Result.factory("User config missing")

        if not rephrase_request_in.config.llm_alternatives:
            response.status_code = status.HTTP_403_FORBIDDEN
            return Result.factory("Rephrasing via LLM not enabled on user")
    else:
        # debug mode
        configs = {}

    context.redis.store_metrics(request, configs, version, "rephrase")

    try:
        result = RephrasesOut.factory(
            rephrase_request_in.sentence,
            await context.llm_alternatives.handle(rephrase_request_in),
        )
    except Exception as e:
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        message = "An error occurred"
        if not version:
            message = f"{message}: {e}"

        return Result.factory(message)

    return result
