"""
Guardrail Routes
Witty GPT for LLM and agent gateways: guidance before the model call, a
verdict and a reask after it. No LLM is called here.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer
from fastapi.security.api_key import APIKeyHeader

from app.auth_service import fetch_user
from app.config_manager import fetch_configs_for_request
from app.context import AppContext
from app.dependencies import get_app_context
from app.guardrail import review
from app.guidance import guidance, merge_guidance
from app.models import (
    BaseRequestIn,
    GuardrailGuidanceOut,
    LangWithAutoType,
    CheckRequestIn,
    Client,
    GuardrailInputIn,
    GuardrailInputOut,
    GuardrailOutputIn,
    GuardrailOutputOut,
)
from app.version_validators import GUARDRAIL_API_VERSION, client_version

router = APIRouter()

CREDENTIALS = [
    Depends(HTTPBearer(auto_error=False)),
    Depends(APIKeyHeader(name="x-key", auto_error=False)),
]

UNAUTHORIZED = {
    401: {"description": "The credential resolves to no user (REQUIRE_AUTH on)"}
}


async def guardrail_user(
    request: Request, request_in: BaseRequestIn, context: AppContext
) -> dict:
    """The configs of whoever the credential resolves to, with
    `request_in.config` resolved. Unlike /v2.4/check a request without a user
    is refused: a guardrail that passed everything on a mistyped key would
    look like one that works. With REQUIRE_AUTH off the deployment answers
    anyone, as /v2.4/check then does, so there is no mistake to hide."""
    client_version(Client.parse(request_in.client), context.settings.minimum_versions)

    user_email = await fetch_user(
        request, context.settings, context.redis, context.http
    )
    if user_email is None:
        if not context.settings.require_auth:
            return await fetch_configs_for_request(request_in, None, context)

        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")

    configs = await fetch_configs_for_request(request_in, user_email, context)
    if not configs:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User config missing")

    return configs


@router.post(
    f"/v{GUARDRAIL_API_VERSION}/guardrail/input",
    response_model=GuardrailInputOut,
    dependencies=CREDENTIALS,
    summary="Add inclusive-language guidance to chat messages",
    responses=UNAUTHORIZED,
)
async def post_guardrail_input(
    request: Request,
    request_in: GuardrailInputIn,
    context: AppContext = Depends(get_app_context),
) -> GuardrailInputOut:
    """Add Witty's inclusive-language guidance to the messages a gateway is
    about to send to its model."""
    configs = await guardrail_user(request, request_in, context)
    context.redis.store_metrics(
        request, configs, GUARDRAIL_API_VERSION, "guardrail_input"
    )

    text = guidance(request_in.config, request_in.lang)

    return GuardrailInputOut(
        messages=merge_guidance(request_in.messages, text), guidance=text
    )


@router.get(
    f"/v{GUARDRAIL_API_VERSION}/guardrail/guidance",
    response_model=GuardrailGuidanceOut,
    dependencies=CREDENTIALS,
    summary="The bare guidance text, for a fixed system prompt",
    responses=UNAUTHORIZED,
)
async def get_guardrail_guidance(
    request: Request,
    lang: LangWithAutoType = LangWithAutoType.AUTO,
    context: AppContext = Depends(get_app_context),
) -> GuardrailGuidanceOut:
    """The guidance /v1.0/guardrail/input adds, for gateways and deployments
    that can only set a fixed system prompt: Kong's prompt decorator, an Azure
    policy, a prompt map."""
    request_in = BaseRequestIn()
    configs = await guardrail_user(request, request_in, context)
    context.redis.store_metrics(
        request, configs, GUARDRAIL_API_VERSION, "guardrail_input"
    )

    return GuardrailGuidanceOut(guidance=guidance(request_in.config, lang))


@router.post(
    f"/v{GUARDRAIL_API_VERSION}/guardrail/output",
    response_model=GuardrailOutputOut,
    response_model_exclude_none=True,
    dependencies=CREDENTIALS,
    summary="Check a model's answer: verdict, findings and reask",
    responses=UNAUTHORIZED,
)
async def post_guardrail_output(
    request: Request,
    request_in: GuardrailOutputIn,
    context: AppContext = Depends(get_app_context),
) -> GuardrailOutputOut:
    """Check a model's answer: a verdict, what was found, and on a fail the
    message for the gateway to send its model."""
    configs = await guardrail_user(request, request_in, context)
    context.redis.store_metrics(
        request, configs, GUARDRAIL_API_VERSION, "guardrail_output"
    )

    check_request_in = CheckRequestIn(
        text=request_in.response,
        lang=request_in.lang,
        client=request_in.client,
        config=request_in.config,
    )

    outcome = await review(check_request_in, configs, context, request_in.threshold)

    # Without `reask` and the findings' empty fields, but with `language: null`
    # where it could not be told: a client reads that key on every answer.
    body = outcome.model_dump(mode="json", exclude_none=True)
    body["language"] = outcome.language
    return JSONResponse(body)
