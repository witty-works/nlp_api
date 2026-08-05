"""
Prompt Routes
Handles LLM prompt processing and review functionality.
"""

from typing import Union

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.security import HTTPBearer
from fastapi.security.api_key import APIKeyHeader

from app.context import AppContext
from app.categories import inclusive_categories
from app.dependencies import (
    fetch_current_username,
    fetch_management_username,
    get_app_context,
)
from app.settings import get_settings
from app.models import CheckRequestIn, PromptOut, Result, ReviewType, Client
from app.version_validators import REPHRASE_API_VERSION
from app.config_manager import fetch_configs_for_request, debug_configs
from app.language_processor import fetch_text, apply_language_rules
from app.review_prompt import ReviewPrompt
from app.routes.check import check

router = APIRouter()


@router.post(
    "/debug/review_prompt",
    response_model=Union[str, Result],
    response_model_exclude_none=True,
    dependencies=[
        Depends(HTTPBearer(auto_error=False)),
        Depends(APIKeyHeader(name="x-key", auto_error=False)),
    ],
    include_in_schema=not get_settings().is_prod,
)
async def debug_review_prompt(
    request: Request,
    response: Response,
    check_request_in: CheckRequestIn,
    context: AppContext = Depends(get_app_context),
    review_type: ReviewType = ReviewType.EXPLAIN_EDITS,
) -> Result | str:
    for category in inclusive_categories:
        if category in check_request_in.config.disabled_categories:
            continue

        check_request_in.config.disabled_categories.append(category)

    check_result = await check(request, response, check_request_in, None, context)
    if isinstance(check_result, Result):
        return check_result

    result = ReviewPrompt.handle(
        check_result.results, review_type, check_request_in.text, 1900
    )
    if result is None:
        result = "WITTYNOCHANGES"

    return result


@router.post(
    "/debug/prompt",
    response_model=Union[Result, PromptOut, None],
    response_model_exclude_none=True,
    include_in_schema=not get_settings().is_prod,
)
async def debug_prompt(
    request: Request,
    response: Response,
    check_request_in: CheckRequestIn,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_current_username),
) -> Result | PromptOut:
    configs = debug_configs(check_request_in)
    return await prompt(response, check_request_in, configs, context)


@router.post(
    f"/v{REPHRASE_API_VERSION}/prompt",
    response_model=Union[Result, PromptOut, None],
    response_model_exclude_none=True,
)
async def post_prompt(
    request: Request,
    response: Response,
    check_request_in: CheckRequestIn,
    user_email: str,
    context: AppContext = Depends(get_app_context),
    username: str = Depends(fetch_management_username),
) -> Result | PromptOut:
    """Run a prompt on a named user's behalf.

    A trusted-caller endpoint rather than a client-facing one: `user_email` is a
    query parameter, so whoever calls this picks whose configuration applies and
    whose LLM budget is spent. That puts it with the management endpoints rather
    than behind the docs switch, which is off by default.
    """
    configs = await fetch_configs_for_request(check_request_in, user_email, context)
    if configs == {}:
        response.status_code = status.HTTP_401_UNAUTHORIZED
        return Result.factory("User config missing")

    context.redis.store_metrics(request, configs, REPHRASE_API_VERSION, "prompt")
    return await prompt(response, check_request_in, configs, context)


async def prompt(
    response: Response,
    check_request_in: CheckRequestIn,
    configs: dict,
    context: AppContext,
) -> Result | PromptOut:
    if not configs:
        response.status_code = status.HTTP_401_UNAUTHORIZED
        return Result.factory("User config missing")

    if not check_request_in.config.llm_alternatives:
        response.status_code = status.HTTP_401_UNAUTHORIZED
        return Result.factory("User config disallows LLM use")

    check_request_in.text = await context.prompt.handle(
        check_request_in.text, None, None, 0.4
    )
    check_request_in.text = context.prompt.parse_json(check_request_in.text)

    for category in inclusive_categories:
        if category in check_request_in.config.disabled_categories:
            continue

        check_request_in.config.disabled_categories.append(category)

    text, language, limit_reached = fetch_text(check_request_in, context.langs, context)

    if language is None:
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        return Result.factory("Language could not be determined")

    client = Client.parse(check_request_in.client)
    check_result = await apply_language_rules(
        client, check_request_in.config, configs, language, text, context
    )

    reviewed_response = None
    if len(check_result) != 0:
        review_prompt = ReviewPrompt.handle(
            check_result, ReviewType.INCLUDE_PREVIOUS, check_request_in.text
        )

        if review_prompt is not None:
            reviewed_response = await context.prompt.handle(review_prompt)
            reviewed_response = context.prompt.parse_json(reviewed_response)

    return PromptOut(
        initial_response=check_request_in.text,
        reviewed_response=reviewed_response,
        check_results=check_result,
        limit_reached=limit_reached,
    )
