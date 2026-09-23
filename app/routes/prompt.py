"""
Prompt Routes
Handles LLM prompt processing and review functionality.
"""

import difflib
import json
import logging
import re
from typing import Union

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.security import HTTPBearer
from fastapi.security.api_key import APIKeyHeader

from app.auth_service import fetch_user
from app.context import AppContext
from app.categories import inclusive_categories
from app.dependencies import (
    fetch_current_username,
    fetch_management_username,
    get_app_context,
)
from app.settings import get_settings
from app.models import (
    CheckRequestIn,
    Client,
    EditOut,
    PromptOut,
    Result,
    ReviewType,
    WriteRequestIn,
)
from app.version_validators import REPHRASE_API_VERSION, client_version
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
    configs = debug_configs(check_request_in, context.settings)
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

    reviewed = await review_draft(check_request_in, configs, context)
    if reviewed is None:
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        return Result.factory("Language could not be determined")

    check_result, reviewed_response, limit_reached = reviewed
    if reviewed_response is not None:
        reviewed_response = context.prompt.parse_json(reviewed_response)

    return PromptOut(
        initial_response=check_request_in.text,
        reviewed_response=reviewed_response,
        check_results=check_result,
        limit_reached=limit_reached,
    )


async def review_draft(
    check_request_in: CheckRequestIn,
    configs: dict,
    context: AppContext,
    max_tokens: int = 300,
) -> tuple[list, str | None, bool] | None:
    """Check what the LLM wrote and have it apply Witty's alternatives.

    Returns the alerts found in the draft, the LLM's raw answer to the review
    (None when there was nothing to fix) and whether the text was cut to the
    check limit. None when the draft's language could not be determined.
    """
    for category in inclusive_categories:
        if category in check_request_in.config.disabled_categories:
            continue

        check_request_in.config.disabled_categories.append(category)

    text, language, limit_reached = fetch_text(check_request_in, context.langs, context)

    if language is None:
        return None

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
            reviewed_response = await context.prompt.handle(
                review_prompt, max_tokens=max_tokens
            )

    return check_result, reviewed_response, limit_reached


# Room for a rewritten text of about the length WriteRequestIn accepts.
WRITE_MAX_TOKENS = 1500


@router.post(
    f"/v{REPHRASE_API_VERSION}/write",
    response_model=Union[PromptOut, Result],
    response_model_exclude_none=True,
    dependencies=[
        Depends(HTTPBearer(auto_error=False)),
        Depends(APIKeyHeader(name="x-key", auto_error=False)),
    ],
)
async def post_write(
    request: Request,
    response: Response,
    write_request_in: WriteRequestIn,
    context: AppContext = Depends(get_app_context),
) -> PromptOut | Result:
    """Write a text, or change the given one, as the prompt says, then review it.

    The client-facing counterpart of /v1.0/prompt: the caller is whoever the
    credential resolves to, so it is gated like /v1.0/rephrase rather than
    behind the management auth. The draft is checked and the LLM asked to apply
    Witty's alternatives, the same review the dashboard's Witty GPT runs.
    """
    client_version(Client.parse(write_request_in.client))

    user_email = await fetch_user(
        request, context.settings, context.redis, context.http
    )
    if user_email is None:
        response.status_code = status.HTTP_401_UNAUTHORIZED
        return Result.factory("User not found")

    configs = await fetch_configs_for_request(write_request_in, user_email, context)
    if not configs:
        response.status_code = status.HTTP_401_UNAUTHORIZED
        return Result.factory("User config missing")

    # `llm_access` has had its say by now, see fetch_configs_for_request.
    if not write_request_in.config.llm_alternatives:
        response.status_code = status.HTTP_403_FORBIDDEN
        return Result.factory("LLM use not enabled on user")

    context.redis.store_metrics(request, configs, REPHRASE_API_VERSION, "write")

    # Witty checks this much of a text at once, so a longer draft would only be
    # reviewed in part; the model is asked to stay inside it, and a draft that
    # does not is reported through `limit_reached`.
    length = (
        f" Keep the result under {context.settings.text_max_length} characters."
    )
    if write_request_in.text.strip():
        user_prompt = (
            "Apply the instruction to the text below. Respond with the complete"
            " revised text only, in the language of the text unless the"
            " instruction asks for another, and keep its paragraph breaks."
            f"{length}\n\n"
            f"Instruction:\n{write_request_in.prompt}\n\n"
            f"Text:\n{write_request_in.text}"
        )
    else:
        user_prompt = (
            f"{write_request_in.prompt}\n\nRespond with the text only.{length}"
        )

    try:
        draft = plain_response(
            await context.prompt.handle(
                user_prompt, None, None, 0.4, max_tokens=WRITE_MAX_TOKENS
            )
        )
        check_request_in = CheckRequestIn(
            text=draft,
            lang=write_request_in.lang,
            client=write_request_in.client,
            config=write_request_in.config,
        )
        reviewed = await review_draft(
            check_request_in, configs, context, WRITE_MAX_TOKENS
        )
    except Exception:
        # The caller gets nothing specific, the operator the whole story: a
        # wrong LLM_API_BASE or an expired provider key ends up here.
        logging.getLogger("nlp_api").exception("/v1.0/write failed")
        response.status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        return Result.factory("An error occurred")

    if reviewed is None:
        response.status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        return Result.factory("Language could not be determined")

    check_result, reviewed_response, limit_reached = reviewed
    if reviewed_response:
        reviewed_response = plain_response(reviewed_response)

    return PromptOut(
        initial_response=draft,
        reviewed_response=reviewed_response or None,
        check_results=check_result,
        limit_reached=limit_reached,
        edits=word_edits(draft, reviewed_response) if reviewed_response else None,
    )


def word_edits(before: str, after: str) -> list[EditOut]:
    """Word diff of the draft against its review, as the dashboard shows it.

    Words and the whitespace between them are the units, so joining the
    non-deleted parts gives `after` back and the non-inserted ones `before`.
    """
    a = [token for token in re.split(r"(\s+)", before) if token]
    b = [token for token in re.split(r"(\s+)", after) if token]

    edits: list[EditOut] = []

    def add(op: str, tokens: list[str]) -> None:
        if not tokens:
            return

        if edits and edits[-1].op == op:
            edits[-1].text += "".join(tokens)
        else:
            edits.append(EditOut(op=op, text="".join(tokens)))

    # No autojunk: it would treat the frequent tokens (spaces, "the") as noise
    # in any text over 200 words and scatter the diff.
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            add("equal", a[i1:i2])
        else:
            add("delete", a[i1:i2])
            add("insert", b[j1:j2])

    return edits


def plain_response(answer: str) -> str:
    """The model's answer as the text itself.

    The review prompt hands the draft over as a JSON string, and models tend to
    answer in kind. Unlike parse_json this leaves braces in prose alone.
    """
    answer = answer.strip()
    if len(answer) >= 2 and answer.startswith('"') and answer.endswith('"'):
        try:
            decoded = json.loads(answer)
        except ValueError:
            return answer

        if isinstance(decoded, str):
            return decoded.strip()

    return answer
