"""
Rephrase Routes
Handles text rephrasing using LLM alternatives.
"""

from typing import Annotated, Union

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import HTTPBearer
from fastapi.security.api_key import APIKeyHeader

from app.prompt import llm_error
from app.llm_access import LlmRefused, llm_user
from app.context import AppContext
from app.dependencies import get_app_context
from app.models import Client, RephraseRequestIn, RephrasesOut, Result
from app.version_validators import (
    client_version,
    rephrase_api_version,
    REPHRASE_API_VERSION,
)

router = APIRouter()


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
    context: Annotated[AppContext, Depends(get_app_context)],
) -> Union[RephrasesOut, Result]:
    return await rephrase_sentence(
        request, response, rephrase_request_in, context, REPHRASE_API_VERSION
    )


async def rephrase_sentence(
    request: Request,
    response: Response,
    rephrase_request_in: RephraseRequestIn,
    context: AppContext,
    version: str,
) -> Union[RephrasesOut, Result]:
    client = Client.parse(rephrase_request_in.client)
    client_version(client, context.settings.minimum_versions)

    rephrase_api_version(version)

    try:
        _, configs = await llm_user(
            request,
            rephrase_request_in,
            context,
            "Rephrasing via LLM not enabled on user",
        )
    except LlmRefused as refused:
        response.status_code = refused.status_code
        return Result.factory(refused.message)

    context.redis.store_metrics(request, configs, version, "rephrase")

    try:
        outcome = await context.llm_alternatives.handle(rephrase_request_in)
        result = RephrasesOut.factory(
            rephrase_request_in.sentence,
            outcome.results,
            outcome.served_model or context.settings.llm_model,
        )
    except Exception as error:
        response.status_code, headers, message = llm_error(error, "/v1.0/rephrase")
        response.headers.update(headers)
        return Result.factory(message)

    return result
