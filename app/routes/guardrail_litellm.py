"""
LiteLLM Guardrail Route
The guardrail endpoints in the format of LiteLLM's Generic Guardrail API
(beta), which calls `{api_base}/beta/litellm_basic_guardrail_api`. LiteLLM has
no reask: a failing answer is annotated or blocked, as the config says.
"""

from fastapi import APIRouter, Depends, Request

from app.context import AppContext
from app.dependencies import get_app_context
from app.guardrail import review
from app.guidance import guidance, merge_guidance
from app.models import (
    CheckRequestIn,
    LitellmGuardrailIn,
    LitellmGuardrailOut,
    ResultOut,
)
from app.routes.guardrail import CREDENTIALS, guardrail_user
from app.version_validators import REPHRASE_API_VERSION

router = APIRouter()


@router.post(
    f"/v{REPHRASE_API_VERSION}/guardrail/litellm/beta/litellm_basic_guardrail_api",
    response_model=LitellmGuardrailOut,
    response_model_exclude_none=True,
    dependencies=CREDENTIALS,
)
async def post_guardrail_litellm(
    request: Request,
    request_in: LitellmGuardrailIn,
    context: AppContext = Depends(get_app_context),
) -> LitellmGuardrailOut:
    """Guidance for a request LiteLLM is about to send, a note or a block for
    the answer it got back."""
    configs = await guardrail_user(request, request_in, context)
    params = request_in.additional_provider_specific_params

    if request_in.input_type == "request":
        context.redis.store_metrics(
            request, configs, REPHRASE_API_VERSION, "guardrail_input"
        )
        return with_guidance(request_in, guidance(request_in.config, params.lang))

    context.redis.store_metrics(
        request, configs, REPHRASE_API_VERSION, "guardrail_output"
    )

    issues = []
    for text in request_in.texts:
        found = None
        if text.strip():
            outcome = await review(
                CheckRequestIn(
                    text=text,
                    lang=params.lang,
                    client=request_in.client,
                    # Each text is reviewed on its own, and a review changes the
                    # config it is given.
                    config=request_in.config.model_copy(deep=True),
                ),
                configs,
                context,
                params.threshold,
            )
            if outcome.verdict == "fail":
                found = issue_list(outcome.findings)
        issues.append(found)

    if not any(issues):
        return LitellmGuardrailOut(action="NONE")

    if params.on_fail == "block":
        return LitellmGuardrailOut(
            action="BLOCKED",
            blocked_reason="Witty: " + "; ".join(i for i in issues if i),
        )

    return LitellmGuardrailOut(
        action="GUARDRAIL_INTERVENED",
        texts=[
            text if found is None else f"{text}\n\n[Witty] {found}"
            for text, found in zip(request_in.texts, issues)
        ],
    )


def with_guidance(request_in: LitellmGuardrailIn, text: str) -> LitellmGuardrailOut:
    """The conversation with the guidance in its system message. Left alone
    where it is there already: a client that keeps its conversation sends it
    back with every turn, and post_call sends the request again."""
    messages = request_in.structured_messages
    if not messages:
        return LitellmGuardrailOut(action="NONE")

    if messages[0].get("role") == "system" and text in str(messages[0].get("content")):
        return LitellmGuardrailOut(action="NONE")

    return LitellmGuardrailOut(
        action="GUARDRAIL_INTERVENED",
        structured_messages=merge_guidance(messages, text),
    )


def issue_list(findings: list[ResultOut]) -> str:
    """`"chairman" → chair / chairperson; ...`, for the findings Witty has
    alternatives for."""
    issues = []
    for finding in findings:
        if not finding.alternatives:
            continue

        alternatives = " / ".join(
            "(remove)" if alternative.remove else alternative.text
            for alternative in finding.alternatives
        )
        issues.append(f'"{finding.text}" → {alternatives}')

    return "; ".join(issues)
