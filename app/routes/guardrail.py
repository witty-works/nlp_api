"""
Guardrail Routes
Witty GPT for LLM and agent gateways: guidance before the model call, a
verdict and a reask after it. No LLM is called here.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer
from fastapi.security.api_key import APIKeyHeader

from app.auth_service import fetch_user
from app.config_manager import fetch_configs_for_request
from app.context import AppContext
from app.dependencies import get_app_context
from app.guardrail import guidance, merge_guidance
from app.models import BaseRequestIn, Client, GuardrailInputIn, GuardrailInputOut
from app.version_validators import REPHRASE_API_VERSION, client_version

router = APIRouter()

CREDENTIALS = [
    Depends(HTTPBearer(auto_error=False)),
    Depends(APIKeyHeader(name="x-key", auto_error=False)),
]


async def guardrail_user(
    request: Request, request_in: BaseRequestIn, context: AppContext
) -> dict:
    """The configs of whoever the credential resolves to, with
    `request_in.config` resolved. Unlike /v2.4/check a request without a user
    is refused: a guardrail that passed everything on a mistyped key would
    look like one that works."""
    client_version(Client.parse(request_in.client), context.settings.minimum_versions)

    user_email = await fetch_user(
        request, context.settings, context.redis, context.http
    )
    if user_email is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")

    configs = await fetch_configs_for_request(request_in, user_email, context)
    if not configs:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User config missing")

    return configs


@router.post(
    f"/v{REPHRASE_API_VERSION}/guardrail/input",
    response_model=GuardrailInputOut,
    dependencies=CREDENTIALS,
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
        request, configs, REPHRASE_API_VERSION, "guardrail_input"
    )

    text = guidance(request_in.config, request_in.lang)

    return GuardrailInputOut(
        messages=merge_guidance(request_in.messages, text), guidance=text
    )
