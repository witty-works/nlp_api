"""
Check Routes
Core text checking functionality with language rules.
"""

from typing import Union

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.security import HTTPBearer
from fastapi.security.api_key import APIKeyHeader

from app.context import AppContext
from app.dependencies import get_app_context
from app.models import CheckRequestIn, Result, ResultsOut, Client
from app.version_validators import (
    client_version,
    check_api_version,
    CHECK_API_VERSION,
)
from app.config_manager import (
    fetch_configs_for_request,
    debug_configs,
    fetch_config_change,
)
from app.language_processor import fetch_text, apply_language_rules
from app.auth_service import fetch_user

router = APIRouter()


@router.post(
    f"/v{CHECK_API_VERSION}/check",
    response_model=Union[ResultsOut, Result],
    response_model_exclude_none=True,
    dependencies=[
        Depends(HTTPBearer(auto_error=False)),
        Depends(APIKeyHeader(name="x-key", auto_error=False)),
    ],
)
async def post_check_v2_4(
    request: Request,
    response: Response,
    check_request_in: CheckRequestIn,
    context: AppContext = Depends(get_app_context),
) -> Union[ResultsOut, Result]:
    return await check(request, response, check_request_in, CHECK_API_VERSION, context)


async def check(
    request: Request,
    response: Response,
    check_request_in: CheckRequestIn,
    version: str | None = None,
    context: AppContext | None = None,
) -> Result | ResultsOut:
    client = Client.parse(check_request_in.client)
    client_version(client)

    user_email = None
    assert context is not None, "AppContext must be provided"
    if version is not None:
        check_api_version(version)

        user_email = await fetch_user(
            request, context.settings, context.redis, context.http
        )
        configs = await fetch_configs_for_request(check_request_in, user_email, context)
    else:
        configs = debug_configs(check_request_in)

    context.redis.store_metrics(request, configs, version, "check")

    context.redis.store_request_log(
        check_request_in,
        user_email,
        request,
        configs,
        version,
        "check",
    )

    if check_request_in.config.plan and check_request_in.config.plan.startswith(
        "witty_"
    ):
        text, language, limit_reached = fetch_text(
            check_request_in, context.langs, context
        )

        if language is None:
            response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
            return Result.factory("Language could not be determined")

        results = await apply_language_rules(
            client, check_request_in.config, configs, language, text, context
        )

        lang = language.lang

        if isinstance(results, Result):
            return results
    else:
        results = []
        # Default to English when plan is not witty_*; use string to align with other paths
        lang = "en"
        limit_reached = False

    notifications = None
    if "notifications" in configs and configs["notifications"] > 0:
        notifications = configs["notifications"]

    has_consented_to_mailing = None
    if "has_consented_to_mailing" in configs:
        has_consented_to_mailing = configs["has_consented_to_mailing"]

    if not isinstance(results, Result):
        results = ResultsOut(
            results=results,
            language=lang,
            limit_reached=limit_reached,
            config_changed=fetch_config_change(configs, check_request_in),
            notifications=notifications,
            has_consented_to_mailing=has_consented_to_mailing,
            gender_separator=check_request_in.config.get_gender_separator(lang),
        )

    context.redis.store_response_log(
        user_email,
        results,
    )

    return results
